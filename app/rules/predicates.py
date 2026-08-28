"""Детерминированные проверки правил матрицы.

Каждая проверка зарегистрирована под именем, которое указывается в поле `check`
файла `config/rules.yaml`. Правила без зарегистрированной проверки остаются
на ручной оценке юриста.

Проверки сознательно строгие: формулировка, которая не читается однозначно,
считается отсутствующей. Ложное срабатывание стоит клиенту лишнего абзаца
в договоре, пропуск — отказа банка.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from app.rules.contract import ContractView

MANDATORY_CONTROL_THRESHOLD = Decimal(10_000_000)
BANK_REGISTRATION_THRESHOLD = Decimal(3_000_000)
TRAVEL_RULE_THRESHOLD = Decimal(60_000)


class Verdict(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class Outcome:
    verdict: Verdict
    evidence: str = ""
    clauses: tuple[str, ...] = field(default_factory=tuple)


Predicate = Callable[[ContractView], Outcome]

_REGISTRY: dict[str, Predicate] = {}


def register(name: str) -> Callable[[Predicate], Predicate]:
    def decorator(function: Predicate) -> Predicate:
        if name in _REGISTRY:
            raise ValueError(f"проверка «{name}» уже зарегистрирована")
        _REGISTRY[name] = function
        return function

    return decorator


def get_predicate(name: str) -> Predicate | None:
    return _REGISTRY.get(name)


def registered_names() -> set[str]:
    return set(_REGISTRY)


def _passed(evidence: str, clauses: tuple[str, ...] = ()) -> Outcome:
    return Outcome(Verdict.PASSED, evidence, clauses)


def _failed(evidence: str, clauses: tuple[str, ...] = ()) -> Outcome:
    return Outcome(Verdict.FAILED, evidence, clauses)


def _skip(evidence: str) -> Outcome:
    return Outcome(Verdict.NOT_APPLICABLE, evidence)


def _clause_numbers(contract: ContractView, *patterns: str) -> tuple[str, ...]:
    return tuple(clause.number for clause in contract.matching_clauses(*patterns))


def _amount(value: Decimal) -> str:
    """Сумма с пробелами между разрядами. Знак рубля не входит в cp1251."""
    return f"{value:,.0f}".replace(",", " ") + " руб."


# --- A. Квалификация договора ---


@register("foreign_trade_qualified")
def foreign_trade_qualified(contract: ContractView) -> Outcome:
    facts = contract.facts
    missing = []
    if not facts.mentions_foreign_trade:
        missing.append("договор не назван внешнеторговым")
    if not facts.mentions_resident:
        missing.append("не указано, что сторона является резидентом")
    if not facts.mentions_non_resident:
        missing.append("не указано, что сторона является нерезидентом")

    if missing:
        return _failed("; ".join(missing))

    return _passed(
        "договор квалифицирован как внешнеторговый между резидентом и нерезидентом",
        _clause_numbers(contract, r"внешнеторгов"),
    )


@register("subject_matter_declared")
def subject_matter_declared(contract: ContractView) -> Outcome:
    patterns = (
        r"передач\w*\s+(товар|информаци|результат)",
        r"поставк\w*",
        r"куп\w*-?\s*продаж\w*",
        r"выполнени\w*\s+работ",
        r"оказани\w*\s+услуг",
    )
    if contract.has_any(*patterns):
        return _passed("предмет договора описан в терминах пункта 1 части 7 статьи 1")

    return _failed(
        "из договора не следует передача товаров, работ, услуг или "
        "результатов интеллектуальной деятельности"
    )


@register("parties_identified")
def parties_identified(contract: ContractView) -> Outcome:
    facts = contract.facts
    if not (facts.mentions_resident and facts.mentions_non_resident):
        return _failed("резидентство сторон из текста не определяется")

    jurisdiction = contract.has_any(
        r"зарегистрирован\w*", r"государств\w*\s+регистрации", r"Федерация", r"Республика"
    )
    identifier = bool(facts.inns) or contract.has_any(
        r"регистрационн\w+\s+номер", r"налогов\w+\s+номер"
    )

    if jurisdiction and identifier:
        return _passed("указаны юрисдикция и регистрационный либо налоговый номер сторон")

    absent = []
    if not jurisdiction:
        absent.append("государство регистрации")
    if not identifier:
        absent.append("регистрационный либо налоговый номер")
    return _failed("не указано: " + ", ".join(absent))


@register("cites_exemption")
def cites_exemption(contract: ContractView) -> Outcome:
    if contract.has_any(
        r"пункт\w*\s+1\s+част\w+\s+7\s+стать\w+\s+1",
        r"ст\.?\s*1\s*ч\.?\s*7\s*п\.?\s*1",
    ):
        return _passed("есть ссылка на пункт 1 части 7 статьи 1 № 282-ФЗ")

    return _failed("нет прямой ссылки на норму, разрешающую расчёты цифровой валютой")


# --- B. Актив ---


@register("asset_identified")
def asset_identified(contract: ContractView) -> Outcome:
    facts = contract.facts
    absent = []
    if not facts.tickers:
        absent.append("тикер цифровой валюты")
    if not facts.networks:
        absent.append("сеть и стандарт токена")
    if not contract.has_any(r"эмитент"):
        absent.append("эмитент")

    if absent:
        return _failed("не указано: " + ", ".join(absent))

    return _passed(
        f"актив идентифицирован: {', '.join(facts.tickers)} в сети {', '.join(facts.networks)}"
    )


@register("payment_purpose_declared")
def payment_purpose_declared(contract: ContractView) -> Outcome:
    if contract.has_any(
        r"расчёт\w*\s+(производятся\s+)?цифров\w+\s+валют",
        r"оплата\s+производится\s+цифровой\s+валютой",
        r"в\s+качестве\s+средства\s+платежа",
        r"встречн\w+\s+предоставлени",
    ):
        return _passed("цифровая валюта заявлена как средство платежа по договору")

    return _failed(
        "не указано, что цифровая валюта используется как средство платежа "
        "по этому договору: депозитарию не на что опереться при зачислении"
    )


# --- C. Адреса и порядок расчётов ---


@register("identifier_address_used")
def identifier_address_used(contract: ContractView) -> Outcome:
    facts = contract.facts
    if facts.wallet_addresses:
        listed = ", ".join(address.value for address in facts.wallet_addresses)
        return _failed(
            f"в договоре указан адрес кошелька вместо адреса-идентификатора: {listed}",
            _clause_numbers(contract, r"T[1-9A-HJ-NP-Za-km-z]{33}|0x[a-fA-F0-9]{40}"),
        )

    if not facts.mentions_identifier_address:
        return _failed("адрес-идентификатор в договоре не упомянут")

    return _passed(
        "расчёты идут через адрес-идентификатор",
        _clause_numbers(contract, r"адрес\w*[\s-]*идентификатор"),
    )


@register("depositary_registry_reference")
def depositary_registry_reference(contract: ContractView) -> Outcome:
    if not contract.facts.mentions_depositary:
        return _failed("цифровой депозитарий не назван")

    if not contract.has_any(r"реестр\w*"):
        return _failed(
            "депозитарий назван, но нет реестровых данных для проверки его права "
            "на деятельность"
        )

    return _passed(
        "депозитарий назван с реестровыми данными",
        _clause_numbers(contract, r"депозитари", r"реестр"),
    )


@register("depositary_statement_right")
def depositary_statement_right(contract: ContractView) -> Outcome:
    if contract.has_all(r"выписк\w+", r"депозитари"):
        return _passed("предусмотрена выписка цифрового депозитария")

    return _failed("нет права требовать выписку цифрового депозитария")


# --- D. Курс и момент исполнения ---


@register("rate_source_fixed")
def rate_source_fixed(contract: ContractView) -> Outcome:
    has_source = contract.has_any(
        r"котировк\w*", r"Московск\w+\s+Бирж", r"Мосбирж", r"Bloomberg", r"курс\w*\s+Банка\s+России"
    )
    has_moment = contract.has_any(
        r"на\s+дату\s+списания", r"на\s+момент\s+списания", r"на\s+дату\s+платежа"
    )

    if has_source and has_moment:
        return _passed("зафиксированы источник котировки и момент её определения")

    absent = []
    if not has_source:
        absent.append("источник котировки")
    if not has_moment:
        absent.append("момент фиксации курса")
    return _failed("не зафиксировано: " + ", ".join(absent))


@register("record_moment_clause")
def record_moment_clause(contract: ContractView) -> Outcome:
    if not contract.facts.mentions_record_moment:
        return _failed(
            "момент исполнения не привязан к внесению записи в информационную "
            "систему: возможен спор при незавершённой транзакции"
        )

    return _passed(
        "исполнение привязано к внесению записи в информационную систему",
        _clause_numbers(contract, r"внесени\w*\s+запис"),
    )


@register("network_fees_allocated")
def network_fees_allocated(contract: ContractView) -> Outcome:
    if contract.has_all(r"комисси\w*", r"(информационн\w+\s+систем|сет)"):
        return _passed("расходы на комиссии информационной системы распределены")

    return _failed("не распределены расходы на комиссии информационной системы")


# --- E. Реквизиты сторон ---


@register("party_details_present")
def party_details_present(contract: ContractView) -> Outcome:
    facts = contract.facts
    absent = []
    if not facts.inns and not contract.has_any(r"налогов\w+\s+номер"):
        absent.append("ИНН либо налоговый номер")
    if not contract.has_any(r"город|\bг\.\s*[А-ЯЁ]"):
        absent.append("город местонахождения")
    if not contract.has_any(r"государств\w*|Федерация|Республика"):
        absent.append("государство местонахождения")

    if absent:
        return _failed(
            "для сопровождения операции не хватает: " + ", ".join(absent)
        )

    return _passed("реквизиты сторон приведены в объёме статьи 7.2-1 № 115-ФЗ")


@register("party_details_above_travel_rule_threshold")
def party_details_above_travel_rule_threshold(contract: ContractView) -> Outcome:
    amount = contract.contract_amount()
    if amount is None:
        return _skip("сумма договора из текста не определена")
    if amount <= TRAVEL_RULE_THRESHOLD:
        return _skip(f"сумма {_amount(amount)} не превышает порог 60 000 руб.")

    return party_details_present(contract)


# --- F. Пороги и контроль ---


@register("mandatory_control_readiness")
def mandatory_control_readiness(contract: ContractView) -> Outcome:
    amount = contract.contract_amount()
    if amount is None:
        return _skip("сумма договора из текста не определена")
    if amount < MANDATORY_CONTROL_THRESHOLD:
        return _skip(f"сумма {_amount(amount)} ниже порога обязательного контроля")

    if contract.has_any(r"подтверждающ\w+\s+документ"):
        return _passed(
            f"сумма {_amount(amount)} подпадает под обязательный контроль; "
            "обязанность предоставлять подтверждающие документы закреплена"
        )

    return _failed(
        f"сумма {_amount(amount)} подпадает под обязательный контроль по пункту 1.12 "
        "статьи 6 № 115-ФЗ, но обязанность предоставлять подтверждающие документы "
        "в договоре не закреплена"
    )


@register("bank_registration_clause")
def bank_registration_clause(contract: ContractView) -> Outcome:
    amount = contract.contract_amount()
    if amount is None:
        return _skip("сумма договора из текста не определена")
    if amount < BANK_REGISTRATION_THRESHOLD:
        return _skip(f"сумма {_amount(amount)} ниже порога постановки на учёт")

    if contract.has_any(r"постановк\w*\s+на\s+учёт", r"на\s+учёт\s+в\s+уполномоченн\w+\s+банк"):
        return _passed("постановка контракта на учёт в уполномоченном банке предусмотрена")

    return _failed(
        f"сумма {_amount(amount)} требует постановки контракта на учёт, "
        "но в договоре это не оговорено"
    )


# --- G. Риски и AML ---


@register("risk_allocation_clause")
def risk_allocation_clause(contract: ContractView) -> Outcome:
    if contract.has_all(r"риск", r"(заморозк|отклонени|приостановлени|блокировк)"):
        return _passed(
            "риски заморозки и отклонения операции распределены",
            _clause_numbers(contract, r"риск"),
        )

    return _failed("не распределены риски заморозки или отклонения операции")


@register("suspension_right")
def suspension_right(contract: ContractView) -> Outcome:
    if contract.has_any(r"приостанов\w+\s+исполнени", r"вправе\s+приостанов"):
        return _passed("предусмотрено право приостановить исполнение")

    return _failed("нет права приостановить исполнение при выявлении риска")


@register("origin_representation")
def origin_representation(contract: ContractView) -> Outcome:
    if contract.has_all(r"заверя\w*", r"(происхожден|не\s+связан)"):
        return _passed("контрагент заверяет о происхождении цифровой валюты")

    return _failed("нет заверения о происхождении цифровой валюты")


# --- H. Документооборот ---


@register("supporting_documents_obligation")
def supporting_documents_obligation(contract: ContractView) -> Outcome:
    if contract.has_any(r"подтверждающ\w+\s+документ"):
        return _passed("обязанность предоставлять подтверждающие документы закреплена")

    return _failed("нет обязанности предоставлять подтверждающие документы")


@register("retention_period")
def retention_period(contract: ContractView) -> Outcome:
    if contract.has_all(r"(пяти|5)\s+лет", r"хран"):
        return _passed("срок хранения документов — не менее пяти лет")

    return _failed("не установлен срок хранения документов по операциям")

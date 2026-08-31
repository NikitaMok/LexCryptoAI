"""Разбор смысла оговорок, которые регулярки не ловят.

Вердикт «соответствует / нет» ставит матрица правил, не модель.
Модель выписывает из текста факты: стороны, агентский договор, депег,
недепозитарный адрес, дробление платежей. Номера статей не называет.
Цитата обязана быть фрагментом договора, иначе отбрасывается.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.llm.client import LlmReply, complete
from app.rules.contract import ContractView
from app.rules.guardrail import CircumventionAttempt, assert_clean, inspect

# Оговорки с нестандартной формулировкой. Вердикт ставит предикат матрицы;
# модель только выписывает факт, если цитата есть в тексте договора.
_CLAUSE_TOPICS = (
    ("FTC-004", "агент, комиссионер, поверенный"),
    ("AST-003", "утрата привязки стейблкоина, делистинг"),
    ("AST-004", "иностранный цифровой инструмент"),
    ("ADR-004", "адрес не администрируемый депозитарием и отчётность в налоговую"),
    ("RTE-004", "предел отклонения курса и доплата"),
    ("TRV-003", "обязанность актуализировать реквизиты"),
    ("THR-003", "график платежей, который выглядит как дробление под порог"),
    ("RPT-004", "содействие в отчёте в налоговые органы"),
)

_MAX_CHARS = 24_000
_ARTICLE_HINT = re.compile(
    r"(?:\d{2,3}-ФЗ|стать[яи]\s+\d+|ст\.\s*\d+\s*ч\.)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PartyNote:
    name: str
    inn: str | None
    role: str


@dataclass(frozen=True)
class ClauseNote:
    code: str
    quote: str
    reading: str
    present: bool | None


@dataclass(frozen=True)
class ClauseAnalysis:
    available: bool
    model: str
    detail: str
    parties: tuple[PartyNote, ...] = ()
    notes: tuple[ClauseNote, ...] = ()

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "model": self.model,
            "detail": self.detail,
            "parties": [
                {"name": item.name, "inn": item.inn, "role": item.role} for item in self.parties
            ],
            "notes": [
                {
                    "code": item.code,
                    "quote": item.quote,
                    "reading": item.reading,
                    "present": item.present,
                }
                for item in self.notes
            ],
        }


def _unavailable(detail: str, model: str = "") -> ClauseAnalysis:
    assert_clean(detail)
    return ClauseAnalysis(available=False, model=model, detail=detail)


def _prompt(text: str) -> str:
    topics = "\n".join(f"- {code}: {title}" for code, title in _CLAUSE_TOPICS)
    body = text if len(text) <= _MAX_CHARS else text[:_MAX_CHARS]
    return (
        "Ниже текст внешнеторгового договора. Выпиши только то, что в нём есть.\n"
        "Не оценивай соответствие закону. Не называй статьи, части и пункты.\n"
        "Не предлагай формулировки договора и способы обойти требование.\n"
        "Если явления в тексте нет — present: false, quote и reading пустые.\n"
        "quote — дословный фрагмент договора, не пересказ.\n\n"
        "Верни JSON вида:\n"
        '{"parties":[{"name":"...","inn":null,"role":"покупатель|поставщик|иное"}],'
        '"notes":[{"code":"FTC-004","present":true,"quote":"...","reading":"..."}]}\n\n'
        "Коды notes — только из списка:\n"
        f"{topics}\n\n"
        "Текст договора:\n"
        f"{body}"
    )


def _grounded_quote(quote: str, contract: str) -> str:
    compact = " ".join(quote.split())
    if len(compact) < 8:
        return ""
    haystack = " ".join(contract.split())
    if compact in haystack:
        return compact
    return ""


def _clean_reading(reading: str) -> str:
    text = " ".join(reading.split())
    if not text:
        return ""
    if _ARTICLE_HINT.search(text):
        return ""
    if inspect(text):
        return ""
    assert_clean(text)
    return text[:500]


def _parse_parties(raw: object, contract: str) -> tuple[PartyNote, ...]:
    if not isinstance(raw, list):
        return ()
    haystack = contract.lower()
    parties: list[PartyNote] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "").split())
        if len(name) < 3 or name.lower() not in haystack:
            continue
        inn_raw = str(item.get("inn") or "").strip()
        inn = inn_raw if inn_raw.isdigit() and inn_raw in contract else None
        role = str(item.get("role") or "иное").strip()[:40]
        try:
            assert_clean(name)
            assert_clean(role)
        except CircumventionAttempt:
            continue
        parties.append(PartyNote(name=name, inn=inn, role=role))
    return tuple(parties)


def _parse_notes(raw: object, contract: str) -> tuple[ClauseNote, ...]:
    allowed = {code for code, _title in _CLAUSE_TOPICS}
    if not isinstance(raw, list):
        return ()
    notes: list[ClauseNote] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if code not in allowed or code in seen:
            continue
        seen.add(code)
        present_raw = item.get("present")
        present: bool | None
        if present_raw is True:
            present = True
        elif present_raw is False:
            present = False
        else:
            present = None
        quote = _grounded_quote(str(item.get("quote") or ""), contract)
        reading = _clean_reading(str(item.get("reading") or ""))
        if present is False:
            quote, reading = "", ""
        notes.append(ClauseNote(code=code, quote=quote, reading=reading, present=present))
    return tuple(notes)


def _from_reply(reply: LlmReply, contract: str) -> ClauseAnalysis:
    if not reply.ok:
        return _unavailable(reply.error or "локальная модель не ответила", reply.model)
    try:
        payload = json.loads(reply.text)
    except json.JSONDecodeError:
        return _unavailable("модель вернула не JSON", reply.model)
    if not isinstance(payload, dict):
        return _unavailable("модель вернула не объект", reply.model)

    parties = _parse_parties(payload.get("parties"), contract)
    notes = _parse_notes(payload.get("notes"), contract)
    detail = "локальная модель разобрала оговорки, которые не ловятся регулярками"
    assert_clean(detail)
    return ClauseAnalysis(
        available=True,
        model=reply.model,
        detail=detail,
        parties=parties,
        notes=notes,
    )


def analyze_clauses(
    contract: ContractView,
    *,
    complete_fn=complete,
) -> ClauseAnalysis:
    reply = complete_fn(_prompt(contract.text))
    if not isinstance(reply, LlmReply):
        return _unavailable("локальная модель не ответила")
    try:
        return _from_reply(reply, contract.text)
    except CircumventionAttempt:
        return _unavailable(
            "ответ модели отклонён: формулировка не проходит проверку части 2 статьи 30",
            reply.model,
        )

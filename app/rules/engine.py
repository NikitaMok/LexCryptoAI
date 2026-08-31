from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from app.rules.contract import ContractView
from app.rules.guardrail import CircumventionAttempt, verify_report
from app.rules.predicates import Verdict, get_predicate
from app.rules.registry import NormRef, Rule, RuleSet, Severity, get_rules

# Основной массив № 282-ФЗ / № 283-ФЗ. Если дату не передали, а сегодня ещё
# раньше — проверяем на день вступления, иначе все правила «с 01.09.2026»
# уйдут в «вступает позднее» и зелёный статус будет ложным.
LAW_IN_FORCE = date(2026, 9, 1)


def default_check_date(moment: date | None = None, *, today: date | None = None) -> date:
    if moment is not None:
        return moment
    now = today or date.today()
    return LAW_IN_FORCE if now < LAW_IN_FORCE else now


class UnknownPredicateError(LookupError):
    pass


class FindingStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"
    # правило спроектировано, но проверяется юристом вручную
    NOT_AUTOMATED = "not_automated"
    # норма ещё не вступила в силу
    DEFERRED = "deferred"


class ContractStatus(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


_VERDICT_TO_STATUS = {
    Verdict.PASSED: FindingStatus.PASSED,
    Verdict.FAILED: FindingStatus.FAILED,
    Verdict.NOT_APPLICABLE: FindingStatus.NOT_APPLICABLE,
    Verdict.UNRESOLVED: FindingStatus.NOT_AUTOMATED,
}


@dataclass(frozen=True)
class Finding:
    code: str
    group: str
    severity: Severity
    title: str
    status: FindingStatus
    evidence: str = ""
    clauses: tuple[str, ...] = ()
    norm_refs: tuple[NormRef, ...] = ()
    sanction: str = ""
    # Формулировка-исправление берётся из матрицы правил и не генерируется:
    # см. app/rules/guardrail.py и ч. 2 ст. 30 № 282-ФЗ.
    recommendation: str = ""

    @property
    def is_violation(self) -> bool:
        return self.status is FindingStatus.FAILED


@dataclass(frozen=True)
class Report:
    status: ContractStatus
    findings: tuple[Finding, ...]
    checked_on: date

    def violations(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.is_violation]

    def blocking_violations(self) -> list[Finding]:
        return [
            finding
            for finding in self.violations()
            if finding.severity is Severity.MANDATORY
        ]

    def advisory_violations(self) -> list[Finding]:
        return [
            finding
            for finding in self.violations()
            if finding.severity is Severity.ADVISORY
        ]

    def needs_manual_review(self) -> list[Finding]:
        return [
            finding
            for finding in self.findings
            if finding.status is FindingStatus.NOT_AUTOMATED
        ]

    def by_code(self, code: str) -> Finding:
        for finding in self.findings:
            if finding.code == code:
                return finding
        raise KeyError(code)


def _evaluate_rule(rule: Rule, contract: ContractView, moment: date) -> Finding:
    common = {
        "code": rule.code,
        "group": rule.group,
        "severity": rule.severity,
        "title": rule.title,
        "norm_refs": tuple(rule.norm_refs),
        "sanction": rule.sanction,
    }

    if not rule.is_active_on(moment):
        evidence = (
            f"норма применяется с {rule.effective_from.isoformat()}"
            if rule.effective_from
            else "норма ещё не введена в действие: ожидается подзаконный акт"
        )
        return Finding(**common, status=FindingStatus.DEFERRED, evidence=evidence)

    if rule.check is None:
        return Finding(
            **common,
            status=FindingStatus.NOT_AUTOMATED,
            evidence="требует оценки юриста",
        )

    predicate = get_predicate(rule.check.predicate)
    if predicate is None:
        raise UnknownPredicateError(
            f"{rule.code}: проверка «{rule.check.predicate}» не зарегистрирована"
        )

    outcome = predicate(contract)
    status = _VERDICT_TO_STATUS[outcome.verdict]

    return Finding(
        **common,
        status=status,
        evidence=outcome.evidence,
        clauses=outcome.clauses,
        recommendation=rule.example_good or "" if status is FindingStatus.FAILED else "",
    )


def _overall_status(findings: tuple[Finding, ...]) -> ContractStatus:
    violations = [finding for finding in findings if finding.is_violation]

    if any(finding.severity is Severity.MANDATORY for finding in violations):
        return ContractStatus.RED
    if violations:
        return ContractStatus.YELLOW
    return ContractStatus.GREEN


def evaluate(
    contract: ContractView,
    rules: RuleSet | None = None,
    moment: date | None = None,
) -> Report:
    ruleset = rules or get_rules()
    checked_on = default_check_date(moment)

    findings = tuple(
        _evaluate_rule(rule, contract, checked_on) for rule in ruleset.rules
    )

    report = Report(
        status=_overall_status(findings),
        findings=findings,
        checked_on=checked_on,
    )

    # Заключение не покидает движок без проверки на советы обойти требование:
    # ч. 2 ст. 30 № 282-ФЗ. Срабатывание означает ошибку в матрице правил,
    # а не проблему проверяемого договора, поэтому падаем громко.
    breaches = verify_report(report)
    if breaches:
        raise CircumventionAttempt(
            "заключение не выдано: " + "; ".join(str(breach) for breach in breaches)
        )

    return report

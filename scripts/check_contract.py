"""Проверка контракта из командной строки.

    python -m scripts.check_contract путь/к/договору.docx
    python -m scripts.check_contract договор.pdf --on 2027-07-01
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from app.parsing.document import EmptyDocumentError, UnsupportedFormatError
from app.rules.contract import ContractView
from app.rules.engine import ContractStatus, Finding, FindingStatus, Report, evaluate

STATUS_LABEL = {
    ContractStatus.GREEN: "ЗЕЛЁНЫЙ — обязательные требования выполнены",
    ContractStatus.YELLOW: "ЖЁЛТЫЙ — есть замечания рекомендательного характера",
    ContractStatus.RED: "КРАСНЫЙ — нарушены обязательные требования",
}

RULE = "-" * 78

# Консоль Windows по умолчанию работает в cp1251: кириллица в неё пишется, но
# любой символ вне кодировки роняет вывод. Заменяем такие символы вместо падения.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")


def _format_norms(finding: Finding) -> str:
    return "; ".join(str(ref) for ref in finding.norm_refs) or "—"


def _print_findings(title: str, findings: list[Finding]) -> None:
    if not findings:
        return

    print(f"\n{title}\n{RULE}")
    for finding in findings:
        print(f"[{finding.code}] {finding.title}")
        if finding.evidence:
            print(f"    {finding.evidence}")
        if finding.clauses:
            print(f"    пункты договора: {', '.join(finding.clauses)}")
        print(f"    норма: {_format_norms(finding)}")
        if finding.sanction:
            print(f"    последствие: {finding.sanction}")
        print()


def print_report(report: Report, source: Path) -> None:
    print(f"\nДокумент: {source.name}")
    print(f"Проверено на дату: {report.checked_on.isoformat()}")
    print(f"Статус: {STATUS_LABEL[report.status]}")

    _print_findings("НАРУШЕНЫ ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ", report.blocking_violations())
    _print_findings("ЗАМЕЧАНИЯ", report.advisory_violations())

    deferred = [f for f in report.findings if f.status is FindingStatus.DEFERRED]
    _print_findings("НОРМЫ, ВСТУПАЮЩИЕ В СИЛУ ПОЗДНЕЕ", deferred)

    manual = report.needs_manual_review()
    if manual:
        print(f"\nТРЕБУЕТ ОЦЕНКИ ЮРИСТА\n{RULE}")
        for finding in manual:
            print(f"[{finding.code}] {finding.title}")

    passed = sum(1 for f in report.findings if f.status is FindingStatus.PASSED)
    skipped = sum(1 for f in report.findings if f.status is FindingStatus.NOT_APPLICABLE)
    print(
        f"\n{RULE}\nИтого правил: {len(report.findings)}. "
        f"Выполнено: {passed}. Нарушено: {len(report.violations())}. "
        f"Не применимо: {skipped}. На ручной оценке: {len(manual)}."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проверка внешнеторгового контракта")
    parser.add_argument("path", type=Path, help="контракт в формате PDF или DOCX")
    parser.add_argument(
        "--on",
        type=date.fromisoformat,
        default=None,
        help="дата, на которую проверяется применимость норм (по умолчанию сегодня)",
    )
    args = parser.parse_args(argv)

    try:
        contract = ContractView.from_file(args.path)
    except (FileNotFoundError, UnsupportedFormatError, EmptyDocumentError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2

    report = evaluate(contract, moment=args.on)
    print_report(report, args.path)

    return 1 if report.status is ContractStatus.RED else 0


if __name__ == "__main__":
    raise SystemExit(main())

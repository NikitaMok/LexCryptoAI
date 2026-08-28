"""Прогон образцовых контрактов. Пишет data/eval/last_run.json (не в git).

    python -m scripts.eval_fixtures
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from app.core.config import PROJECT_ROOT
from app.rules.contract import ContractView
from app.rules.engine import ContractStatus, FindingStatus, evaluate

FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
OUT = PROJECT_ROOT / "data" / "eval" / "last_run.json"
LAW_IN_FORCE = date(2026, 9, 1)


def _run(path: Path) -> dict:
    report = evaluate(ContractView.from_file(path), moment=LAW_IN_FORCE)
    return {
        "source": path.name,
        "status": report.status.value,
        "blocking": [finding.code for finding in report.blocking_violations()],
        "passed": sum(1 for finding in report.findings if finding.status is FindingStatus.PASSED),
        "manual": [finding.code for finding in report.needs_manual_review()],
    }


def main() -> int:
    compliant = _run(FIXTURES / "contract_compliant.docx")
    violating = _run(FIXTURES / "contract_violating.docx")
    payload = {
        "checked_on": LAW_IN_FORCE.isoformat(),
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "compliant": compliant,
        "violating": violating,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"образцовый: {compliant['status']}, выполнено {compliant['passed']}")
    print(
        f"нарушающий: {violating['status']}, "
        f"обязательных нарушений {len(violating['blocking'])}"
    )
    print(f"запись: {OUT}")

    if compliant["status"] != ContractStatus.GREEN.value:
        return 1
    if violating["status"] != ContractStatus.RED.value:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

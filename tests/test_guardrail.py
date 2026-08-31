from datetime import date
from pathlib import Path

import pytest

from app.rules.contract import ContractView
from app.rules.engine import FindingStatus, evaluate
from app.rules.guardrail import (
    CircumventionAttempt,
    assert_clean,
    inspect,
    verify_report,
)
from app.rules.registry import load_rules

LAW_IN_FORCE = date(2026, 9, 1)


@pytest.fixture(scope="module")
def rules():
    return load_rules()


class TestCatchesCircumvention:
    @pytest.mark.parametrize(
        "text",
        [
            "Разбейте сумму на два платежа, чтобы не превышать порог обязательного контроля.",
            "Оформите поставку так, чтобы банк не заметил расчёты цифровой валютой.",
            "Можно обойти требование о постановке на учёт.",
            "Проще не указывать в договоре цифровую валюту.",
            "Рекомендуется скрыть назначение платежа.",
            "Оформите фиктивный договор оказания услуг.",
            "Достаточно занизить сумму контракта.",
            "Проведите операцию без постановки на учёт.",
            "Формально соблюсти требование и работать в серой зоне.",
            "Так можно избежать обязательного контроля.",
        ],
    )
    def test_advice_to_circumvent_is_flagged(self, text):
        findings = inspect(text)

        assert findings, f"не поймано: {text}"
        assert findings[0].reason

    def test_assert_clean_raises_with_explanation(self):
        with pytest.raises(CircumventionAttempt) as error:
            assert_clean("Раздробите платежи, чтобы не превышать порог.", context="ответ модели")

        assert "обойти требование" in str(error.value)
        assert "ответ модели" in str(error.value)

    def test_catches_across_line_breaks(self):
        """Перенос строки не должен прятать формулировку от проверки."""
        findings = inspect("следует обойти\nтребование о постановке на учёт")

        assert findings


class TestAllowsLegitimateText:
    @pytest.mark.parametrize(
        "text",
        [
            "Отсутствуют признаки искусственного дробления платежей для ухода из-под порога.",
            "Операция подлежит обязательному контролю в случае, если сумма равна или "
            "превышает 10 миллионов рублей.",
            "Покупатель обеспечивает постановку настоящего Договора на учёт "
            "в уполномоченном банке.",
            "Квалификация операций как подозрительных; блокировка.",
            "Депозитарий обязан отказать в исполнении поручения.",
            "Не распределены риски заморозки или отклонения операции.",
            "Сумма 12 000 000 руб. не ниже порога постановки на учёт "
            "импортного контракта по пункту 4.3 Инструкции Банка России № 181-И, "
            "но в договоре это не оговорено.",
        ],
    )
    def test_descriptive_wording_passes(self, text):
        assert inspect(text) == []

    def test_matrix_content_is_clean(self, rules):
        """Собственные тексты матрицы обязаны проходить проверку."""
        breaches = []
        for rule in rules.rules:
            for field in (rule.title, rule.sanction, rule.example_bad, rule.example_good):
                breaches.extend(inspect(field or "", rule.code))

        assert not breaches, "; ".join(str(breach) for breach in breaches)


class TestReportIsVerifiedBeforeRelease:
    def test_clean_report_passes(self, violating_docx: Path, rules):
        report = evaluate(ContractView.from_file(violating_docx), rules, moment=LAW_IN_FORCE)

        assert verify_report(report) == []

    def test_tampered_rule_blocks_the_whole_report(self, violating_docx: Path, rules):
        """Если в матрицу попадёт совет обойти закон, заключение не выдаётся."""
        tampered = load_rules()
        target = next(rule for rule in tampered.rules if rule.code == "THR-002")
        target.sanction = "Можно обойти требование о постановке на учёт."

        with pytest.raises(CircumventionAttempt) as error:
            evaluate(ContractView.from_file(violating_docx), tampered, moment=LAW_IN_FORCE)

        assert "заключение не выдано" in str(error.value)
        assert "THR-002" in str(error.value)


class TestRecommendationsComeFromMatrix:
    def test_failed_rule_carries_vetted_wording(self, violating_docx: Path, rules):
        report = evaluate(ContractView.from_file(violating_docx), rules, moment=LAW_IN_FORCE)
        finding = report.by_code("ADR-001")

        assert finding.status is FindingStatus.FAILED
        assert "адрес-идентификатор" in finding.recommendation
        assert finding.recommendation == rules.by_group("C")[0].example_good

    def test_passed_rule_has_no_recommendation(self, compliant_docx: Path, rules):
        report = evaluate(ContractView.from_file(compliant_docx), rules, moment=LAW_IN_FORCE)

        for finding in report.findings:
            if finding.status is not FindingStatus.FAILED:
                assert finding.recommendation == ""

    def test_recommendations_are_never_generated_outside_matrix(
        self, violating_docx: Path, rules
    ):
        report = evaluate(ContractView.from_file(violating_docx), rules, moment=LAW_IN_FORCE)
        vetted = {rule.example_good for rule in rules.rules if rule.example_good}

        for finding in report.findings:
            if finding.recommendation:
                assert finding.recommendation in vetted

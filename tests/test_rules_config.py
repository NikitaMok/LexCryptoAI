import re
from datetime import date

import pytest

from app.core.config import PROJECT_ROOT
from app.rules.registry import Severity, load_rules

SPEC_PATH = PROJECT_ROOT / "docs" / "RULES_SPEC.md"

LAW_IN_FORCE = date(2026, 9, 1)


@pytest.fixture(scope="module")
def rules():
    return load_rules()


@pytest.fixture(scope="module")
def spec_text():
    return SPEC_PATH.read_text(encoding="utf-8")


def test_ruleset_loads_and_validates(rules):
    assert rules.rules
    assert rules.groups


def test_every_group_has_rules(rules):
    empty = [group for group in rules.groups if not rules.by_group(group)]

    assert not empty, f"группы без правил: {empty}"


def test_mandatory_rules_reference_norms(rules):
    without_norms = [
        rule.code for rule in rules.mandatory() if not rule.norm_refs
    ]

    assert not without_norms


def test_codes_follow_naming_convention(rules):
    malformed = [
        rule.code for rule in rules.rules if not re.fullmatch(r"[A-Z]{3}-\d{3}", rule.code)
    ]

    assert not malformed


def test_spec_and_config_declare_the_same_codes(rules, spec_text):
    spec_codes = set(re.findall(r"`([A-Z]{3}-\d{3})`", spec_text))

    assert spec_codes == rules.codes, (
        f"только в спецификации: {sorted(spec_codes - rules.codes)}; "
        f"только в конфиге: {sorted(rules.codes - spec_codes)}"
    )


def test_spec_summary_matches_config(rules, spec_text):
    """Сводная таблица в разделе 12 спецификации не должна расходиться с конфигом."""
    declared_total = re.search(r"\*\*Итого\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|\s*\*\*(\d+)\*\*", spec_text)

    assert declared_total, "в спецификации не найдена строка «Итого» сводной таблицы"

    total, mandatory = (int(value) for value in declared_total.groups())

    assert total == len(rules.rules)
    assert mandatory == len(rules.mandatory())


def test_deferred_rules_are_documented(rules, spec_text):
    """Правило с датой позже вступления закона должно быть объяснено в спецификации."""
    for rule in rules.rules:
        if rule.effective_from is None or rule.effective_from > LAW_IN_FORCE:
            assert rule.code in spec_text, (
                f"{rule.code} отложено или не активно, но не описано в спецификации"
            )


def test_activity_split_on_law_entry_date(rules):
    active = rules.active_on(LAW_IN_FORCE)
    deferred = rules.deferred(LAW_IN_FORCE)

    assert len(active) + len(deferred) == len(rules.rules)
    assert active, "на дату вступления закона в силу нет ни одного активного правила"


def test_examples_present_for_key_mandatory_rules(rules):
    """Правила, по которым чаще всего ошибаются, обязаны иметь примеры формулировок."""
    codes_needing_examples = {"FTC-001", "AST-001", "ADR-001", "RTE-002"}
    by_code = {rule.code: rule for rule in rules.rules}

    for code in codes_needing_examples:
        rule = by_code[code]

        assert rule.example_bad, f"{code}: нет примера нарушения"
        assert rule.example_good, f"{code}: нет примера исправления"
        assert rule.severity is Severity.MANDATORY

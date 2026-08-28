from __future__ import annotations

from datetime import date
from enum import Enum
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

from app.core.config import PROJECT_ROOT

RULES_PATH = PROJECT_ROOT / "config" / "rules.yaml"


class Severity(str, Enum):
    MANDATORY = "mandatory"
    ADVISORY = "advisory"


class NormRef(BaseModel):
    act: str
    ref: str

    def __str__(self) -> str:
        return f"{self.act}, {self.ref}"


class Rule(BaseModel):
    code: str
    group: str
    severity: Severity
    title: str
    sanction: str
    norm_refs: list[NormRef] = []
    # None означает, что норма ещё не введена в действие: правило хранится
    # в матрице неактивным и активируется при появлении подзаконного акта
    effective_from: date | None = None
    check: dict | None = None
    example_bad: str | None = None
    example_good: str | None = None

    @model_validator(mode="after")
    def mandatory_rule_needs_norm(self) -> Rule:
        if self.severity is Severity.MANDATORY and not self.norm_refs:
            raise ValueError(f"{self.code}: обязательное правило без ссылки на норму")
        return self

    def is_active_on(self, moment: date) -> bool:
        return self.effective_from is not None and self.effective_from <= moment


class RuleSet(BaseModel):
    version: str
    updated: date
    legal_basis: list[str]
    groups: dict[str, str]
    rules: list[Rule]

    @model_validator(mode="after")
    def validate_consistency(self) -> RuleSet:
        codes = [rule.code for rule in self.rules]
        duplicates = {code for code in codes if codes.count(code) > 1}
        if duplicates:
            raise ValueError(f"дублирующиеся коды правил: {sorted(duplicates)}")

        unknown = {rule.group for rule in self.rules} - set(self.groups)
        if unknown:
            raise ValueError(f"правила ссылаются на неизвестные группы: {sorted(unknown)}")

        return self

    @property
    def codes(self) -> set[str]:
        return {rule.code for rule in self.rules}

    def mandatory(self) -> list[Rule]:
        return [rule for rule in self.rules if rule.severity is Severity.MANDATORY]

    def active_on(self, moment: date) -> list[Rule]:
        return [rule for rule in self.rules if rule.is_active_on(moment)]

    def deferred(self, moment: date) -> list[Rule]:
        return [rule for rule in self.rules if not rule.is_active_on(moment)]

    def by_group(self, group: str) -> list[Rule]:
        return [rule for rule in self.rules if rule.group == group]


def load_rules(path: Path | None = None) -> RuleSet:
    source = path or RULES_PATH
    with source.open(encoding="utf-8") as handle:
        return RuleSet.model_validate(yaml.safe_load(handle))


@lru_cache
def get_rules() -> RuleSet:
    return load_rules()

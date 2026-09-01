"""Снимок перечня государств, не выполняющих рекомендации ФАТФ.

Источник и дата снимка лежат в YAML. Это не перечень Правительства РФ:
его на дату снимка нет. Приказ Росфинмониторинга № 361 — отдельный акт
(Иран и КНДР); Мьянма есть только в снимке ФАТФ. Заключение не делает вид,
что российский перечень Правительства опубликован.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.core.config import PROJECT_ROOT

LIST_PATH = PROJECT_ROOT / "config" / "fatf_jurisdictions.yaml"


@dataclass(frozen=True)
class Jurisdiction:
    iso2: str
    names: tuple[str, ...]
    in_rf_order_361: bool = False


@dataclass(frozen=True)
class FatfSnapshot:
    as_of: str
    source: str
    source_url: str
    jurisdictions: tuple[Jurisdiction, ...]

    def match_in(self, text: str) -> list[Jurisdiction]:
        found: list[Jurisdiction] = []
        for jurisdiction in self.jurisdictions:
            if any(pattern.search(text) for pattern in _patterns_for(jurisdiction)):
                found.append(jurisdiction)
        return found


def _patterns_for(jurisdiction: Jurisdiction) -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for name in sorted(jurisdiction.names, key=len, reverse=True):
        compiled.append(re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.IGNORECASE))
    return tuple(compiled)


def load_fatf_snapshot(path: Path | None = None) -> FatfSnapshot:
    source = path or LIST_PATH
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    jurisdictions = tuple(
        Jurisdiction(
            iso2=item["iso2"],
            names=tuple(item["names"]),
            in_rf_order_361=bool(item.get("in_rf_order_361")),
        )
        for item in raw["jurisdictions"]
    )
    if not jurisdictions:
        raise ValueError("снимок перечня ФАТФ пуст")
    return FatfSnapshot(
        as_of=str(raw["as_of"]),
        source=str(raw["source"]),
        source_url=str(raw["source_url"]),
        jurisdictions=jurisdictions,
    )


@lru_cache
def get_fatf_snapshot() -> FatfSnapshot:
    return load_fatf_snapshot()

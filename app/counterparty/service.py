"""Сборка сверки контрагента из фактов договора."""

from __future__ import annotations

from collections.abc import Callable

from app.counterparty.models import PartyCheck, summarize
from app.counterparty.providers import lookup_free_sources
from app.llm.clauses import PartyNote
from app.parsing.extract import PartyMention
from app.rules.contract import ContractView
from app.rules.guardrail import assert_clean

Lookup = Callable[..., tuple]


def _foreign_name(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ("ltd", "inc", "gmbh", "llc", "co."))


def _merge_parties(
    mentions: list[PartyMention],
    llm_parties: tuple[PartyNote, ...],
) -> list[tuple[str, str | None]]:
    by_inn: dict[str, str] = {}
    nameless: list[str] = []
    for item in mentions:
        if item.inn:
            by_inn.setdefault(item.inn, item.name)
        elif item.name:
            nameless.append(item.name)
    for item in llm_parties:
        if item.inn:
            by_inn.setdefault(item.inn, item.name)
        elif item.name and item.name not in nameless and item.name not in by_inn.values():
            nameless.append(item.name)

    rows: list[tuple[str, str | None]] = [
        (name or f"ИНН {inn}", inn) for inn, name in by_inn.items()
    ]
    for name in nameless:
        rows.append((name, None))
    return rows


def review_counterparties(
    contract: ContractView,
    *,
    llm_parties: tuple[PartyNote, ...] = (),
    lookup: Lookup | None = None,
) -> list[PartyCheck]:
    rows = _merge_parties(contract.facts.parties, llm_parties)
    if not rows:
        summary = "в тексте нет ИНН и наименования стороны; сверка не выполнена"
        assert_clean(summary)
        return [
            PartyCheck(name="", inn=None, foreign=False, hits=(), summary=summary)
        ]

    fetch = lookup or lookup_free_sources
    checks: list[PartyCheck] = []
    for name, inn in rows:
        foreign = (not inn) and _foreign_name(name)
        hits = tuple(fetch(inn, name, foreign=foreign))
        summary = summarize(hits, foreign=foreign, has_inn=bool(inn))
        checks.append(
            PartyCheck(name=name, inn=inn, foreign=foreign, hits=hits, summary=summary)
        )
    return checks

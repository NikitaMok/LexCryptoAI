"""Скоринг адресов, извлечённых из контракта."""

from __future__ import annotations

from collections.abc import Callable

from app.aml.providers import fetch_snapshots, paid_wallet_notes
from app.aml.score import AddressScore, AddressSnapshot, score_snapshot
from app.core.config import get_settings
from app.rules.contract import ContractView
from app.rules.guardrail import assert_clean

Lookup = Callable[..., list[AddressSnapshot]]


def score_contract_addresses(
    contract: ContractView,
    *,
    lookup: Lookup | None = None,
    threshold: int | None = None,
) -> list[AddressScore]:
    addresses = contract.facts.wallet_addresses
    if not addresses:
        return []

    snapshots = (lookup or fetch_snapshots)(addresses)
    limit = threshold if threshold is not None else get_settings().aml_risk_threshold
    extras = paid_wallet_notes()
    for fragment in extras:
        assert_clean(fragment)
    scores = [score_snapshot(snapshot, threshold=limit) for snapshot in snapshots]
    if not extras:
        return scores
    return [
        AddressScore(
            address=item.address,
            network=item.network,
            score=item.score,
            band=item.band,
            factors=item.factors,
            labels=item.labels,
            disclaimer=item.disclaimer,
            error=item.error,
            source_notes=extras,
        )
        for item in scores
    ]

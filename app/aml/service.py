"""Скоринг адресов, извлечённых из контракта."""

from __future__ import annotations

from collections.abc import Callable

from app.aml.providers import fetch_snapshots
from app.aml.score import AddressScore, AddressSnapshot, score_snapshot
from app.core.config import get_settings
from app.rules.contract import ContractView

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
    return [score_snapshot(snapshot, threshold=limit) for snapshot in snapshots]

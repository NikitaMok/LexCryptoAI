"""Один прогон: договор → локальная модель → правила → кошелёк → контрагент."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from app.aml.score import AddressScore
from app.aml.service import score_contract_addresses
from app.counterparty.models import PartyCheck
from app.counterparty.service import review_counterparties
from app.llm.clauses import ClauseAnalysis, analyze_clauses
from app.rules.contract import ContractView
from app.rules.engine import Report, evaluate


@dataclass(frozen=True)
class CheckResult:
    report: Report
    source_name: str
    llm: ClauseAnalysis
    address_scores: tuple[AddressScore, ...]
    counterparties: tuple[PartyCheck, ...]


def run_check(
    contract: ContractView,
    *,
    source_name: str,
    moment: date | None = None,
    analyze: Callable[..., ClauseAnalysis] | None = None,
    score_addresses: Callable[..., list[AddressScore]] | None = None,
    review_parties: Callable[..., list[PartyCheck]] | None = None,
) -> CheckResult:
    llm = (analyze or analyze_clauses)(contract)
    report = evaluate(contract, moment=moment)
    scores = (score_addresses or score_contract_addresses)(contract)
    parties = (review_parties or review_counterparties)(
        contract, llm_parties=llm.parties
    )
    return CheckResult(
        report=report,
        source_name=source_name,
        llm=llm,
        address_scores=tuple(scores),
        counterparties=tuple(parties),
    )

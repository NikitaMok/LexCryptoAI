from datetime import date, datetime, timezone
from decimal import Decimal

import httpx

from app.aml.fatf import load_fatf_snapshot
from app.aml.score import AddressSnapshot, score_snapshot
from app.parsing.document import Document, SourceFormat
from app.rules.contract import ContractView
from app.rules.engine import FindingStatus, evaluate
from app.rules.predicates import Verdict, fatf_jurisdiction_addressed

LAW_IN_FORCE = date(2026, 9, 1)


def _view(text: str) -> ContractView:
    lines = [line for line in text.strip().split("\n") if line.strip()]
    return ContractView.from_document(Document(SourceFormat.DOCX, lines))


class TestFatfSnapshot:
    def test_contains_three_call_for_action_states(self):
        snapshot = load_fatf_snapshot()

        assert snapshot.as_of == "2026-06-19"
        assert {item.iso2 for item in snapshot.jurisdictions} == {"KP", "IR", "MM"}

    def test_matches_iran_and_ignores_china(self):
        snapshot = load_fatf_snapshot()

        assert snapshot.match_in("биржа зарегистрирована в Иране")
        assert not snapshot.match_in("поставщик из Китайской Народной Республики")


class TestFatfPredicate:
    def test_unresolved_when_jurisdiction_is_unnamed(self):
        outcome = fatf_jurisdiction_addressed(_view("1.1. Оплата USDT через депозитарий."))

        assert outcome.verdict is Verdict.UNRESOLVED
        assert "Правительства РФ" in outcome.evidence

    def test_fails_when_listed_state_is_named_without_clause(self):
        outcome = fatf_jurisdiction_addressed(
            _view("1.1. Адрес администрирует организация, зарегистрированная в Иране.")
        )

        assert outcome.verdict is Verdict.FAILED
        assert "Иран" in outcome.evidence

    def test_passes_when_fatf_clause_present(self):
        outcome = fatf_jurisdiction_addressed(
            _view(
                "1.1. Адрес-идентификатор не администрируется организацией из государства, "
                "не выполняющего рекомендации ФАТФ. Если иное будет установлено, "
                "операция подлежит обязательному контролю независимо от суммы."
            )
        )

        assert outcome.verdict is Verdict.PASSED

    def test_compliant_contract_stays_on_lawyer_review(self, compliant_docx):
        report = evaluate(ContractView.from_file(compliant_docx), moment=LAW_IN_FORCE)

        assert report.by_code("AML-002").status is FindingStatus.NOT_AUTOMATED
        assert report.status.value == "green"


class TestAddressScore:
    def test_new_empty_address_is_high_risk(self):
        snapshot = AddressSnapshot(
            address="TTEST",
            network="TRON",
            created_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
            tx_count=0,
            usdt_balance=Decimal(0),
        )

        result = score_snapshot(
            snapshot,
            threshold=50,
            now=datetime(2026, 8, 29, tzinfo=timezone.utc),
        )

        assert result.score is not None and result.score >= 50
        assert result.band == "высокий"
        assert result.disclaimer

    def test_lookup_error_does_not_invent_a_score(self):
        result = score_snapshot(
            AddressSnapshot(address="0x1", network="EVM", error="ключ Etherscan не задан")
        )

        assert result.score is None
        assert result.band == "нет данных"


class TestGoPlusLabels:
    def test_public_labels_raise_the_band(self):
        snapshot = AddressSnapshot(
            address="0xabc",
            network="EVM",
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            tx_count=50,
            usdt_balance=Decimal(100),
            risk_labels=("фишинг", "миксер"),
        )

        result = score_snapshot(
            snapshot,
            threshold=50,
            now=datetime(2026, 8, 29, tzinfo=timezone.utc),
        )

        assert result.band == "высокий"
        assert "фишинг" in result.factors[0] or any("фишинг" in item for item in result.factors)
        assert result.labels == ("фишинг", "миксер")


class TestGoPlusFetch:
    def test_merges_labels_onto_tron_snapshot(self):
        from app.aml.providers import fetch_snapshot
        from app.parsing.extract import WalletAddress

        def handler(request: httpx.Request) -> httpx.Response:
            if "gopluslabs" in str(request.url):
                return httpx.Response(
                    200,
                    json={"result": {"phishing_activities": "1", "sanctioned": "0"}},
                )
            if "accounts" in str(request.url) and "transactions" not in str(request.url):
                return httpx.Response(200, json={"data": []})
            return httpx.Response(200, json={"data": []})

        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport) as client:
            snapshot = fetch_snapshot(
                WalletAddress(value="TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE", network="TRON"),
                client,
            )

        assert "фишинг" in snapshot.risk_labels

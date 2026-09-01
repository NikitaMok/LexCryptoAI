from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def compliant_docx(fixtures_dir: Path) -> Path:
    return fixtures_dir / "contract_compliant.docx"


@pytest.fixture(scope="session")
def compliant_pdf(fixtures_dir: Path) -> Path:
    return fixtures_dir / "contract_compliant.pdf"


@pytest.fixture(scope="session")
def violating_docx(fixtures_dir: Path) -> Path:
    return fixtures_dir / "contract_violating.docx"


@pytest.fixture(autouse=True)
def stub_pipeline_network(monkeypatch, request):
    """В unit-тестах Ollama, реестры и RPC не дергаем. Живые вызовы — в test_llm / test_counterparty / test_aml с транспортом-заглушкой."""
    if request.node.get_closest_marker("no_pipeline_stub"):
        return

    from app.llm.clauses import ClauseAnalysis

    def fake_llm(contract):
        return ClauseAnalysis(
            available=False,
            model="",
            detail="в тестах локальная модель не вызывается",
        )

    monkeypatch.setattr("app.pipeline.analyze_clauses", fake_llm)
    monkeypatch.setattr("app.pipeline.score_contract_addresses", lambda contract: [])
    monkeypatch.setattr(
        "app.pipeline.review_counterparties",
        lambda contract, llm_parties=(): _offline_parties(contract),
    )


def _offline_parties(contract):
    from app.counterparty.service import review_counterparties

    return review_counterparties(
        contract,
        lookup=lambda inn, name, client=None, **_: (),
    )


@pytest.fixture
def cyrillic_font():
    from app.report.pdf import MissingCyrillicFontError, resolve_font

    try:
        return resolve_font()
    except MissingCyrillicFontError:
        pytest.skip("нет TTF-шрифта с кириллицей")

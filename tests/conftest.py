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

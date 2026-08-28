from datetime import date
from io import BytesIO
from pathlib import Path

import pdfplumber

from app.report.pdf import DISCLAIMER, FOOTER, TITLE, render_pdf, write_pdf
from app.rules.contract import ContractView
from app.rules.engine import evaluate
from app.rules.guardrail import inspect
from scripts.check_contract import main

LAW_IN_FORCE = date(2026, 9, 1)


def _text(data: bytes) -> str:
    with pdfplumber.open(BytesIO(data)) as document:
        return "\n".join(page.extract_text() or "" for page in document.pages)


class TestPdfContent:
    def test_static_wording_is_clean(self):
        for fragment in (TITLE, DISCLAIMER, FOOTER):
            assert inspect(fragment) == []

    def test_violating_contract_pdf_names_blocking_rules(
        self, violating_docx: Path, cyrillic_font
    ):
        report = evaluate(ContractView.from_file(violating_docx), moment=LAW_IN_FORCE)
        text = _text(render_pdf(report, source_name=violating_docx.name))

        assert "КРАСНЫЙ" in text
        assert "[ADR-001]" in text
        assert "2.3" in text
        assert "юридической консультацией" in text
        assert "цифровым анализом" in text

    def test_cli_writes_pdf(self, compliant_docx: Path, tmp_path, capsys, cyrillic_font):
        output = tmp_path / "заключение.pdf"
        code = main(
            [str(compliant_docx), "--on", "2026-09-01", "--pdf", str(output)]
        )
        capsys.readouterr()

        assert code == 0
        assert output.is_file()
        assert output.read_bytes().startswith(b"%PDF")
        assert "ЗЕЛЁНЫЙ" in _text(output.read_bytes())

    def test_write_pdf_creates_file(self, compliant_docx: Path, tmp_path, cyrillic_font):
        report = evaluate(ContractView.from_file(compliant_docx), moment=LAW_IN_FORCE)
        path = tmp_path / "out.pdf"
        write_pdf(report, path, source_name="договор.docx")

        assert path.stat().st_size > 1000

from decimal import Decimal
from pathlib import Path

import pytest

from app.parsing.document import (
    EmptyDocumentError,
    SourceFormat,
    UnsupportedFormatError,
    load_document,
    normalize,
)
from app.parsing.extract import extract_amounts, extract_facts
from app.parsing.structure import find_clauses, split_clauses


class TestLoading:
    def test_loads_docx(self, compliant_docx: Path):
        document = load_document(compliant_docx)

        assert document.source_format is SourceFormat.DOCX
        assert document.paragraphs
        assert "внешнеторговым договором" in document.text

    def test_loads_pdf(self, compliant_pdf: Path):
        document = load_document(compliant_pdf)

        assert document.source_format is SourceFormat.PDF
        assert document.page_count and document.page_count >= 1
        assert "внешнеторговым договором" in document.text

    def test_rejects_unsupported_format(self, tmp_path: Path):
        unsupported = tmp_path / "contract.txt"
        unsupported.write_text("текст", encoding="utf-8")

        with pytest.raises(UnsupportedFormatError):
            load_document(unsupported)

    def test_rejects_missing_file(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_document(tmp_path / "нет-такого.docx")

    def test_rejects_document_without_text_layer(self, tmp_path: Path):
        from docx import Document as DocxDocument

        empty = tmp_path / "scan.docx"
        DocxDocument().save(str(empty))

        with pytest.raises(EmptyDocumentError):
            load_document(empty)


class TestNormalization:
    def test_joins_hyphenated_line_break(self):
        assert normalize("внешне-\nторговый") == "внешнеторговый"

    def test_replaces_non_breaking_space(self):
        assert normalize("12\u00a0000\u00a0000 рублей") == "12 000 000 рублей"

    def test_drops_soft_hyphen(self):
        assert normalize("депози\u00adтарий") == "депозитарий"

    def test_collapses_blank_runs(self):
        assert normalize("а\n\n\n\n\nб") == "а\n\nб"


class TestStructure:
    def test_splits_numbered_clauses(self, compliant_docx: Path):
        clauses = split_clauses(load_document(compliant_docx))
        numbers = [clause.number for clause in clauses]

        assert "1.1" in numbers
        assert "3.3" in numbers

    def test_levels_and_children(self, compliant_docx: Path):
        clauses = split_clauses(load_document(compliant_docx))
        by_number = {clause.number: clause for clause in clauses}

        assert by_number["3"].level == 1
        assert by_number["3"].is_section
        assert by_number["3.2"].level == 2
        assert "3.2" in by_number["3"].children

    def test_section_heading_recognized(self, compliant_docx: Path):
        clauses = split_clauses(load_document(compliant_docx))
        by_number = {clause.number: clause for clause in clauses}

        assert by_number["3"].heading == "ЦЕНА И ПОРЯДОК РАСЧЁТОВ"

    def test_sum_is_not_parsed_as_clause_number(self, compliant_docx: Path):
        """«12 000 000 рублей» не должно превратиться в пункт 12."""
        clauses = split_clauses(load_document(compliant_docx))

        assert "12" not in {clause.number for clause in clauses}

    def test_find_clauses_by_pattern(self, compliant_docx: Path):
        clauses = split_clauses(load_document(compliant_docx))

        found = find_clauses(clauses, r"адрес\w*[\s-]*идентификатор")

        assert found
        assert any(clause.number.startswith("3.") for clause in found)


class TestAmounts:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("12 000 000 рублей", Decimal(12_000_000)),
            ("12 000 000 (двенадцать миллионов) рублей", Decimal(12_000_000)),
            ("10 млн рублей", Decimal(10_000_000)),
            ("500 тыс. руб.", Decimal(500_000)),
            ("3 000 000 RUB", Decimal(3_000_000)),
        ],
    )
    def test_parses_russian_amount_formats(self, text: str, expected: Decimal):
        amounts = extract_amounts(text)

        assert amounts
        assert amounts[0].value == expected
        assert amounts[0].currency == "RUB"

    def test_distinguishes_currency(self):
        amounts = extract_amounts("150 000 USDT и 12 000 000 рублей")
        currencies = {amount.currency for amount in amounts}

        assert currencies == {"USDT", "RUB"}

    def test_max_amount_drives_threshold_rules(self, compliant_docx: Path):
        facts = extract_facts(load_document(compliant_docx).text)

        assert facts.max_amount("RUB") == Decimal(12_000_000)


class TestFacts:
    def test_compliant_contract_uses_identifier_address(self, compliant_docx: Path):
        facts = extract_facts(load_document(compliant_docx).text)

        assert facts.mentions_identifier_address
        assert facts.mentions_depositary
        assert not facts.wallet_addresses

    def test_violating_contract_exposes_raw_wallet(self, violating_docx: Path):
        facts = extract_facts(load_document(violating_docx).text)

        assert facts.wallet_addresses
        assert facts.wallet_addresses[0].network == "TRON"
        assert not facts.mentions_identifier_address

    def test_asset_identification(self, compliant_docx: Path):
        facts = extract_facts(load_document(compliant_docx).text)

        assert "USDT" in facts.tickers
        assert "TRC-20" in facts.networks

    def test_violating_contract_lacks_asset_identification(self, violating_docx: Path):
        facts = extract_facts(load_document(violating_docx).text)

        assert not facts.tickers
        assert not facts.networks

    def test_foreign_trade_markers(self, compliant_docx: Path):
        facts = extract_facts(load_document(compliant_docx).text)

        assert facts.mentions_foreign_trade
        assert facts.mentions_resident
        assert facts.mentions_non_resident

    def test_violating_contract_lacks_qualification(self, violating_docx: Path):
        facts = extract_facts(load_document(violating_docx).text)

        assert not facts.mentions_foreign_trade
        assert not facts.mentions_non_resident

    def test_record_moment_clause(self, compliant_docx: Path, violating_docx: Path):
        assert extract_facts(load_document(compliant_docx).text).mentions_record_moment
        assert not extract_facts(load_document(violating_docx).text).mentions_record_moment

    def test_inn_extracted(self, compliant_docx: Path):
        facts = extract_facts(load_document(compliant_docx).text)

        assert "6659123456" in facts.inns


def test_pdf_and_docx_give_the_same_legal_picture(compliant_docx: Path, compliant_pdf: Path):
    """Формат загрузки не должен влиять на результат проверки."""
    from_docx = extract_facts(load_document(compliant_docx).text)
    from_pdf = extract_facts(load_document(compliant_pdf).text)

    assert set(from_docx.tickers) == set(from_pdf.tickers)
    assert set(from_docx.networks) == set(from_pdf.networks)
    assert from_docx.max_amount("RUB") == from_pdf.max_amount("RUB")
    assert from_docx.inns == from_pdf.inns
    assert from_docx.mentions_identifier_address == from_pdf.mentions_identifier_address
    assert from_docx.mentions_foreign_trade == from_pdf.mentions_foreign_trade

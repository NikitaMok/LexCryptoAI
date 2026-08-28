from pathlib import Path

from scripts.check_contract import main


class TestExitCodes:
    def test_compliant_contract_returns_zero(self, compliant_docx: Path, capsys):
        code = main([str(compliant_docx), "--on", "2026-09-01"])
        output = capsys.readouterr().out

        assert code == 0
        assert "ЗЕЛЁНЫЙ" in output

    def test_violating_contract_returns_one(self, violating_docx: Path, capsys):
        code = main([str(violating_docx), "--on", "2026-09-01"])
        output = capsys.readouterr().out

        assert code == 1
        assert "КРАСНЫЙ" in output

    def test_unsupported_format_returns_two(self, tmp_path: Path, capsys):
        unsupported = tmp_path / "договор.txt"
        unsupported.write_text("текст", encoding="utf-8")

        code = main([str(unsupported)])

        assert code == 2
        assert "Ошибка" in capsys.readouterr().err

    def test_missing_file_returns_two(self, tmp_path: Path):
        assert main([str(tmp_path / "нет.docx")]) == 2


class TestOutput:
    def test_violations_reference_clause_numbers(self, violating_docx: Path, capsys):
        main([str(violating_docx), "--on", "2026-09-01"])
        output = capsys.readouterr().out

        assert "[ADR-001]" in output
        assert "пункты договора: 2.3" in output

    def test_norm_text_is_quoted_verbatim(self, violating_docx: Path, capsys):
        main([str(violating_docx), "--on", "2026-09-01", "--quote-norms"])
        output = capsys.readouterr().out

        assert "по внешнеторговым договорам" in output
        assert "10 миллионов" in output

    def test_norm_text_is_omitted_by_default(self, violating_docx: Path, capsys):
        main([str(violating_docx), "--on", "2026-09-01"])
        output = capsys.readouterr().out

        assert "норма: 282-ФЗ, ст. 1 ч. 7 п. 1" in output
        assert "по внешнеторговым договорам" not in output

    def test_unverified_norm_is_marked_not_invented(self, violating_docx: Path, capsys):
        """По Инструкции 181-И текста нет — это должно быть сказано прямо."""
        main([str(violating_docx), "--on", "2026-09-01", "--quote-norms"])
        output = capsys.readouterr().out

        assert "текст не выверен" in output

    def test_deferred_and_manual_blocks_present(self, compliant_docx: Path, capsys):
        main([str(compliant_docx), "--on", "2026-09-01"])
        output = capsys.readouterr().out

        assert "НОРМЫ, ВСТУПАЮЩИЕ В СИЛУ ПОЗДНЕЕ" in output
        assert "ТРЕБУЕТ ОЦЕНКИ ЮРИСТА" in output
        assert "Итого правил: 32" in output

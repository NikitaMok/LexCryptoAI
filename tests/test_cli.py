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

    def test_instruction_threshold_is_quoted(self, violating_docx: Path, capsys):
        main([str(violating_docx), "--on", "2026-09-01", "--quote-norms"])
        output = capsys.readouterr().out

        assert "181-И, п. 4.3" in output
        assert "3 млн рублей" in output
        assert "требует сверки редакции" not in output

    def test_article_7_point_2_is_quoted_not_invented(self, capsys):
        from app.norms.index import NormIndex

        found = NormIndex.load().resolve_ref("115-ФЗ", "ст. 7 п. 2")
        assert found
        assert found[0].has_text
        assert "уклонение от процедур обязательного контроля" in found[0].text

        code = main(["--search", "уклонение от процедур обязательного контроля"])
        output = capsys.readouterr().out
        assert code == 0
        assert "уклонение от процедур обязательного контроля" in output
        assert "текст не выверен" not in output

    def test_deferred_block_present_on_compliant(self, compliant_docx: Path, capsys):
        main([str(compliant_docx), "--on", "2026-09-01"])
        output = capsys.readouterr().out

        assert "НОРМЫ, ВСТУПАЮЩИЕ В СИЛУ ПОЗДНЕЕ" in output
        assert "Итого правил: 32" in output

    def test_unresolved_fatf_listed_as_manual_on_violating(self, violating_docx: Path, capsys):
        main([str(violating_docx), "--on", "2026-09-01"])
        output = capsys.readouterr().out

        assert "ТРЕБУЕТ ОЦЕНКИ ЮРИСТА" in output
        assert "AML-002" in output


class TestSearch:
    def test_finds_norm_by_wording(self, capsys):
        code = main(["--search", "внешнеторговый договор резидент нерезидент"])
        output = capsys.readouterr().out

        assert code == 0
        assert "282-ФЗ" in output
        assert "ст. 1" in output
        assert "внешнеторгов" in output.lower()

    def test_empty_result_is_stated(self, capsys):
        code = main(["--search", "xyzzy-несуществующая-формулировка-qwerty"])
        output = capsys.readouterr().out

        assert code == 0
        assert "Ничего не найдено" in output

import pytest

from app.norms.index import Citation, NormIndex
from app.rules.registry import load_rules

# Нормы, процитированные в матрице, но не выверенные по действующей редакции.
# Список должен только сокращаться. Новая запись здесь означает осознанный
# пробел, а не забытую сверку.
ACKNOWLEDGED_GAPS = {
    ("115-ФЗ", "7"),
    ("181-И", "требует сверки редакции"),
}


@pytest.fixture(scope="module")
def norms():
    return NormIndex.load()


@pytest.fixture(scope="module")
def rules():
    return load_rules()


class TestCitationParsing:
    @pytest.mark.parametrize(
        ("ref", "expected"),
        [
            ("ст. 17", ("17", None, None, None)),
            ("ст. 1 ч. 7 п. 1", ("1", "7", "1", None)),
            ("ст. 24 ч. 1-2", ("24", "1-2", None, None)),
            ("ст. 6 п. 1.12", ("6", None, "1.12", None)),
            ("ст. 7.2-1 п. 1 подп. 2", ("7.2-1", None, "1", "2")),
            ("ст. 3 ч. 7-8", ("3", "7-8", None, None)),
            ("ст. 35 ч. 1", ("35", "1", None, None)),
        ],
    )
    def test_parses_matrix_formats(self, ref, expected):
        citation = Citation.parse("282-ФЗ", ref)

        assert citation is not None
        assert (citation.article, citation.part, citation.point, citation.subpoint) == expected

    def test_rejects_non_citation(self):
        assert Citation.parse("181-И", "требует сверки редакции") is None

    def test_readable_representation(self):
        citation = Citation.parse("282-ФЗ", "ст. 1 ч. 7 п. 1")

        assert str(citation) == "282-ФЗ, ст. 1 ч. 7 п. 1"


class TestCorpus:
    def test_corpus_is_loaded(self, norms):
        assert len(norms) > 100
        assert {"282-ФЗ", "115-ФЗ", "173-ФЗ"} <= norms.acts

    def test_every_citation_in_matrix_resolves(self, norms, rules):
        unresolved = []
        for rule in rules.rules:
            for ref in rule.norm_refs:
                citation = Citation.parse(ref.act, ref.ref)
                found = norms.resolve(citation) if citation else norms.resolve_ref(
                    ref.act, ref.ref
                )
                if not found and (ref.act, ref.ref) not in ACKNOWLEDGED_GAPS:
                    unresolved.append(f"{rule.code}: {ref.act}, {ref.ref}")

        assert not unresolved, "ссылки не разрешаются в текст нормы: " + "; ".join(unresolved)

    def test_gaps_are_declared_not_silent(self, norms):
        """Норма без текста обязана объяснять, почему текста нет."""
        for act, article in ACKNOWLEDGED_GAPS:
            found = [
                norm
                for norm in norms.resolve(Citation(act=act, article=article))
                if not norm.has_text
            ] or [
                norm
                for norm in NormIndex.load()._norms
                if norm.act == act and norm.article == article
            ]

            assert found, f"пробел {act} ст. {article} не описан в корпусе"
            assert all(norm.note for norm in found if not norm.has_text)

    def test_no_untracked_empty_texts(self, norms):
        empty = {
            (norm.act, norm.article)
            for norm in NormIndex.load()._norms
            if not norm.has_text
        }

        assert empty == ACKNOWLEDGED_GAPS, (
            f"появились необъявленные пробелы: {sorted(empty - ACKNOWLEDGED_GAPS)}"
        )


class TestKeyNormsAreVerbatim:
    """Ключевые для продукта нормы должны цитироваться дословно."""

    def test_foreign_trade_exemption(self, norms):
        found = norms.resolve_ref("282-ФЗ", "ст. 1 ч. 7 п. 1")

        assert found
        assert "внешнеторговым договорам" in found[0].text

    def test_mandatory_control_threshold(self, norms):
        found = norms.resolve_ref("115-ФЗ", "ст. 6 п. 1.12")

        assert found
        assert "10 миллионов рублей" in found[0].text
        assert "внешнеторговым договорам" in found[0].text

    def test_travel_rule_threshold(self, norms):
        found = norms.resolve_ref("115-ФЗ", "ст. 7.2-1 п. 1")

        assert found
        assert "60 000 рублей" in found[0].text

    def test_execution_moment(self, norms):
        found = norms.resolve_ref("282-ФЗ", "ст. 30 ч. 3")

        assert found
        assert "внесения записи" in found[0].text

    def test_depositary_statement_confirms_holding(self, norms):
        found = norms.resolve_ref("282-ФЗ", "ст. 24 ч. 4")

        assert found
        assert "выпиской цифрового депозитария" in found[0].text

    def test_repatriation_requirement_is_optional(self, norms):
        found = norms.resolve_ref("173-ФЗ", "ст. 19 ч. 9")

        assert found
        assert "может быть установлено требование о репатриации" in found[0].text

    def test_tax_reporting_obligation(self, norms):
        found = norms.resolve_ref("173-ФЗ", "ст. 12.1 ч. 2")

        assert found
        assert "налоговые органы" in found[0].text


class TestResolutionNarrowing:
    def test_range_matches_every_part(self, norms):
        found = norms.resolve_ref("282-ФЗ", "ст. 24 ч. 1-2")
        parts = {norm.part for norm in found}

        assert parts == {"1", "2"}

    def test_article_without_part_returns_whole_article(self, norms):
        found = norms.resolve_ref("282-ФЗ", "ст. 17")

        assert len(found) > 1
        assert all(norm.article == "17" for norm in found)

    def test_unknown_article_resolves_to_nothing(self, norms):
        assert norms.resolve_ref("282-ФЗ", "ст. 999 ч. 1") == []

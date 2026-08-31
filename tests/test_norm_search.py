import pytest

from app.norms.search import LexicalNormSearch, stem, tokenize


@pytest.fixture(scope="module")
def search():
    return LexicalNormSearch.from_index()


class TestTokenization:
    def test_keeps_hyphenated_legal_terms(self):
        tokens = tokenize("адрес-идентификатор")

        assert any("идентификатор" in token for token in tokens)
        assert len(tokens) == 1

    def test_normalizes_yo(self):
        assert tokenize("учёт") == tokenize("учет")

    def test_drops_service_vocabulary(self):
        assert tokenize("в соответствии с настоящим Федеральным законом") == []

    def test_case_insensitive(self):
        assert tokenize("ДЕПОЗИТАРИЙ") == tokenize("депозитарий")

    @pytest.mark.parametrize(
        ("forms"),
        [
            ("депозитарий", "депозитария", "депозитарию", "депозитарии"),
            ("резидент", "резидента", "резиденты", "резидентами"),
            ("норма", "нормы", "норме", "нормами"),
        ],
    )
    def test_word_forms_share_a_stem(self, forms):
        stems = {stem(form) for form in forms}

        assert len(stems) == 1, f"формы разошлись: {stems}"

    def test_short_words_are_not_mutilated(self):
        assert stem("учёт".replace("ё", "е")) == "учет"


class TestSearch:
    def test_corpus_is_indexed(self, search):
        assert len(search) > 100

    @pytest.mark.parametrize(
        ("query", "expected_fragment"),
        [
            ("оплата товара по внешнеторговому контракту цифровой валютой", "внешнеторгов"),
            ("подтверждение владения цифровой валютой выпиской", "выписк"),
            ("требование о репатриации цифровых валют", "репатриа"),
            ("когда операция попадает под обязательный контроль", "обязательному контролю"),
            ("отчёт в налоговые органы об операциях", "налоговые органы"),
        ],
    )
    def test_finds_relevant_norm(self, search, query, expected_fragment):
        hits = search.search(query, limit=5)

        assert hits
        assert any(expected_fragment in hit.norm.text.lower() for hit in hits), [
            hit.norm.reference for hit in hits
        ]

    def test_word_form_does_not_break_the_match(self, search):
        """Падеж в запросе не должен менять результат."""
        by_nominative = search.search("цифровой депозитарий", limit=5)
        by_dative = search.search("цифровому депозитарию", limit=5)

        assert {hit.norm.reference for hit in by_nominative} == {
            hit.norm.reference for hit in by_dative
        }

    def test_synonym_query_is_a_known_limitation(self, search):
        """Лексический поиск не связывает «возврат валюты» и «репатриацию».

        Ровно этот разрыв закрывается поиском по эмбеддингам: слои дополняют
        друг друга, а не заменяют.
        """
        hits = search.search("возврат валюты в Россию", limit=5)

        assert not any("репатриа" in hit.norm.text.lower() for hit in hits)

    def test_results_are_ordered_by_score(self, search):
        hits = search.search("цифровой депозитарий адрес-идентификатор", limit=10)

        scores = [hit.score for hit in hits]

        assert scores == sorted(scores, reverse=True)

    def test_limit_is_respected(self, search):
        assert len(search.search("цифровая валюта", limit=3)) <= 3

    def test_can_narrow_to_one_act(self, search):
        hits = search.search("обязательный контроль операции", limit=10, act="115-ФЗ")

        assert hits
        assert {hit.norm.act for hit in hits} == {"115-ФЗ"}

    def test_empty_query_returns_nothing(self, search):
        assert search.search("") == []
        assert search.search("в и на с по") == []

    def test_nonsense_query_returns_nothing(self, search):
        assert search.search("абракадабра квазимодо") == []

    def test_gap_entries_are_not_searchable(self, search):
        """Нормы без выверенного текста не должны попадать в выдачу."""
        hits = search.search("внутренний контроль уклонение обязательного контроля", limit=20)

        assert all(hit.norm.has_text for hit in hits)
        assert all(not (hit.norm.act == "115-ФЗ" and hit.norm.article == "7" and not hit.norm.has_text) for hit in hits)

    def test_instruction_threshold_is_searchable(self, search):
        hits = search.search("постановка на учет импортных контрактов 3 млн", limit=10)

        assert any(hit.norm.act == "181-И" and hit.norm.article == "4.3" for hit in hits)

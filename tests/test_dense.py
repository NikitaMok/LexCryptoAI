from app.norms.dense import DenseNormSearch, _cosine
from app.norms.index import Norm


def test_cosine_of_equal_vectors_is_one():
    assert abs(_cosine([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9


def test_search_ranks_by_vector_proximity():
    first = Norm(act="282-ФЗ", article="1", article_title="", text="репатриация")
    second = Norm(act="282-ФЗ", article="2", article_title="", text="депозитарий")
    search = DenseNormSearch(
        [first, second],
        [[1.0, 0.0], [0.0, 1.0]],
        encode_query=lambda query: [1.0, 0.0] if "возврат" in query else [0.0, 1.0],
    )

    hits = search.search("возврат валюты", limit=2)

    assert hits[0].norm.article == "1"

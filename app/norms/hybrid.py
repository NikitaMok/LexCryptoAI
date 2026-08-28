"""Слияние лексической и векторной выдачи методом Reciprocal Rank Fusion.

Слои не заменяют друг друга: BM25 ловит совпадение слов, эмбеддинги —
формулировки без общих лексем. Итоговый порядок — по сумме 1/(k + ранг).
"""

from __future__ import annotations

from app.norms.search import SearchHit, get_search

RRF_K = 60


def fuse(*rankings: list[SearchHit], limit: int = 5, k: int = RRF_K) -> list[SearchHit]:
    scores: dict[str, float] = {}
    by_key: dict[str, SearchHit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            key = hit.norm.reference
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            by_key[key] = hit
    ordered = sorted(scores, key=lambda key: (-scores[key], key))
    return [
        SearchHit(norm=by_key[key].norm, score=scores[key])
        for key in ordered[:limit]
    ]


def hybrid_search(
    query: str,
    limit: int = 5,
    act: str | None = None,
    *,
    use_dense: bool | None = None,
) -> list[SearchHit]:
    pool = max(limit * 4, 12)
    lexical = get_search().search(query, limit=pool, act=act)
    dense_hits: list[SearchHit] = []
    want_dense = use_dense
    try:
        from app.core.config import get_settings
        from app.norms.dense import dense_available, get_dense

        if want_dense is None:
            want_dense = get_settings().dense_search
        if want_dense and dense_available():
            dense_hits = get_dense().search(query, limit=pool, act=act)
    except Exception:
        dense_hits = []

    if not dense_hits:
        return lexical[:limit]
    return fuse(lexical, dense_hits, limit=limit)

"""Поиск нормы по смыслу формулировки.

Нужен там, где BM25 не сходится: в запросе нет слов из текста нормы.
Образец разрыва — «возврат валюты в Россию» и репатриация.

Модель не входит в обязательные зависимости и не ставится в CI.
Если пакета или весов нет, слой молча не участвует: лексический поиск
продолжает работать.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.norms.index import Norm, NormIndex
from app.norms.search import SearchHit

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def dense_available() -> bool:
    try:
        import fastembed  # noqa: F401
    except ImportError:
        return False
    return True


def _cosine(left: list[float], right: list[float]) -> float:
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right, strict=True):
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm ** 0.5 * right_norm ** 0.5)


class DenseNormSearch:
    def __init__(
        self,
        norms: list[Norm],
        vectors: list[list[float]],
        encode_query,
    ) -> None:
        if len(norms) != len(vectors):
            raise ValueError("число векторов не совпадает с числом норм")
        self._norms = norms
        self._vectors = vectors
        self._encode_query = encode_query

    def __len__(self) -> int:
        return len(self._norms)

    def search(self, query: str, limit: int = 5, act: str | None = None) -> list[SearchHit]:
        text = query.strip()
        if not text or not self._vectors:
            return []

        query_vector = self._encode_query(text)
        scored: list[SearchHit] = []
        for norm, vector in zip(self._norms, self._vectors, strict=True):
            if act is not None and norm.act != act:
                continue
            score = _cosine(query_vector, vector)
            if score > 0:
                scored.append(SearchHit(norm=norm, score=score))
        scored.sort(key=lambda hit: (-hit.score, hit.norm.reference))
        return scored[:limit]

    @classmethod
    def from_index(
        cls,
        index: NormIndex | None = None,
        model_name: str | None = None,
    ) -> DenseNormSearch:
        from fastembed import TextEmbedding

        source = index or NormIndex.load()
        usable = [norm for norm in source._norms if norm.has_text]  # noqa: SLF001
        name = model_name or get_settings().embedding_model or DEFAULT_MODEL
        model = TextEmbedding(model_name=name)
        vectors = [list(map(float, vector)) for vector in model.embed(norm.text for norm in usable)]

        def encode_query(text: str) -> list[float]:
            return list(map(float, next(model.embed([text]))))

        return cls(usable, vectors, encode_query)


@lru_cache
def get_dense() -> DenseNormSearch:
    return DenseNormSearch.from_index()

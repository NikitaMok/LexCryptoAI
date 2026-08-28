"""Поиск нормы по формулировке, когда точной ссылки нет.

Первый слой корпуса — точное разрешение ссылки «ст. 1 ч. 7 п. 1» в текст
(`app/norms/index.py`). Этот модуль нужен там, где ссылки нет: формулировка
в договоре нечёткая, и надо предложить, к какой норме её подтянуть.

Реализован лексический поиск BM25 с отсечением русских окончаний. Он
не требует моделей и работает всюду, где работает сам сервис. Поиск
по эмбеддингам подключается тем же методом `search` и уточняет результат там,
где формулировки расходятся лексически.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from app.norms.index import Norm, NormIndex

_TOKEN = re.compile(r"[а-яa-z0-9]+(?:-[а-яa-z0-9]+)*")

# Служебная лексика нормативных текстов: встречается почти в каждой норме
# и только шумит при поиске.
_STOPWORDS = frozenset(
    """
    и в на с по для что или не а но к о от до за из при если как то же бы ли это
    том числе также иных иные иное иная ином иными настоящего настоящим настоящей
    настоящему настоящее российской федерации федерального федеральным закона
    законом законе статьи статье статьей части часть пункта пункт быть был была
    может могут вправе обязан обязаны такой такие таких такого случае случаях
    порядке соответствии установленных установленном предусмотренных лица лиц
    лицом лицами их его ее а также осуществляется осуществляют
    """.split()
)

# Порядок задаётся длиной, а не записью: иначе «депозитарию» отсечётся до
# «депозитари» по окончанию «ю», а «депозитария» — до «депозитар» по «ия»,
# и падежи одного слова перестанут совпадать при поиске.
_ENDINGS = tuple(
    sorted(
        {
            "иями", "иях", "иям", "ием", "ией",
            "ями", "ами", "ого", "его", "ому", "ему", "ыми", "ими", "ных", "ный",
            "ия", "ию", "ии", "ий", "ие", "ая", "яя", "ое", "ее", "ой", "ей",
            "ый", "ом", "ем", "ах", "ях", "ов", "ев", "ам", "ям", "ые", "ых",
            "ут", "ют", "ат", "ят", "ть",
            "у", "ю", "а", "я", "о", "е", "ы", "и", "й", "ь",
        },
        key=len,
        reverse=True,
    )
)

_MIN_STEM = 4

K1 = 1.5
B = 0.75


def stem(token: str) -> str:
    """Отсечение окончания. Грубее морфологического анализатора, но без словарей."""
    for ending in _ENDINGS:
        if token.endswith(ending) and len(token) - len(ending) >= _MIN_STEM:
            return token[: -len(ending)]
    return token


def tokenize(text: str) -> list[str]:
    lowered = text.lower().replace("ё", "е")
    return [
        stem(token)
        for token in _TOKEN.findall(lowered)
        if token not in _STOPWORDS and len(token) > 1
    ]


@dataclass(frozen=True)
class SearchHit:
    norm: Norm
    score: float

    def __str__(self) -> str:
        return f"{self.norm.reference} ({self.score:.2f})"


class LexicalNormSearch:
    """BM25 по корпусу норм."""

    def __init__(self, norms: list[Norm]) -> None:
        self._norms = [norm for norm in norms if norm.has_text]
        self._documents = [Counter(tokenize(norm.text)) for norm in self._norms]
        self._lengths = [sum(document.values()) for document in self._documents]
        self._average_length = (
            sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        )

        frequency: Counter[str] = Counter()
        for document in self._documents:
            frequency.update(document.keys())
        self._document_frequency = frequency

    @classmethod
    def from_index(cls, index: NormIndex | None = None) -> LexicalNormSearch:
        source = index or NormIndex.load()
        return cls(source._norms)  # noqa: SLF001 — корпус читается целиком по смыслу

    def __len__(self) -> int:
        return len(self._norms)

    def _inverse_document_frequency(self, term: str) -> float:
        total = len(self._documents)
        containing = self._document_frequency.get(term, 0)
        if containing == 0:
            return 0.0
        return math.log(1 + (total - containing + 0.5) / (containing + 0.5))

    def search(self, query: str, limit: int = 5, act: str | None = None) -> list[SearchHit]:
        terms = tokenize(query)
        if not terms or not self._documents:
            return []

        weights = {term: self._inverse_document_frequency(term) for term in set(terms)}
        scored: list[SearchHit] = []

        for position, document in enumerate(self._documents):
            norm = self._norms[position]
            if act is not None and norm.act != act:
                continue

            length = self._lengths[position] or 1
            score = 0.0
            for term in set(terms):
                occurrences = document.get(term, 0)
                if not occurrences:
                    continue
                normalization = K1 * (1 - B + B * length / (self._average_length or 1))
                score += weights[term] * occurrences * (K1 + 1) / (occurrences + normalization)

            if score > 0:
                scored.append(SearchHit(norm=norm, score=score))

        scored.sort(key=lambda hit: (-hit.score, hit.norm.reference))
        return scored[:limit]


@lru_cache
def get_search() -> LexicalNormSearch:
    return LexicalNormSearch.from_index()

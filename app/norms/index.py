"""Разрешение ссылки из матрицы правил в текст нормы.

Ссылка вида «ст. 1 ч. 7 п. 1» превращается в структуру и ищется в корпусе
`data/curated/norms.jsonl`. Если текста нормы в корпусе нет, это видно явно:
запись с пустым текстом и пояснением, почему её нет. Пересказывать норму
по памяти нельзя — в заключении для банка цитируется только выверенный текст.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import PROJECT_ROOT

NORMS_PATH = PROJECT_ROOT / "data" / "curated" / "norms.jsonl"

_CITATION = re.compile(
    r"^ст\.?\s*(?P<article>[\d.\-]+)"
    r"(?:\s+ч\.?\s*(?P<part>[\d\-]+))?"
    r"(?:\s+п\.?\s*(?P<point>[\d.\-]+))?"
    r"(?:\s+подп\.?\s*(?P<subpoint>[\d.а-я\-]+))?$"
)


def _expand_range(value: str | None) -> list[str | None]:
    """«1-2» превращается в ['1', '2'], одиночное значение остаётся собой."""
    if value is None:
        return [None]
    if "-" not in value:
        return [value]

    start, _, end = value.partition("-")
    if start.isdigit() and end.isdigit() and int(start) <= int(end):
        return [str(number) for number in range(int(start), int(end) + 1)]
    return [value]


@dataclass(frozen=True)
class Citation:
    act: str
    article: str
    part: str | None = None
    point: str | None = None
    subpoint: str | None = None

    @classmethod
    def parse(cls, act: str, ref: str) -> Citation | None:
        match = _CITATION.match(ref.strip())
        if not match:
            return None

        return cls(
            act=act,
            article=match.group("article"),
            part=match.group("part"),
            point=match.group("point"),
            subpoint=match.group("subpoint"),
        )

    def __str__(self) -> str:
        tail = "".join(
            filter(
                None,
                (
                    f" ч. {self.part}" if self.part else "",
                    f" п. {self.point}" if self.point else "",
                    f" подп. {self.subpoint}" if self.subpoint else "",
                ),
            )
        )
        return f"{self.act}, ст. {self.article}{tail}"


@dataclass(frozen=True)
class Norm:
    act: str
    article: str
    article_title: str
    text: str
    part: str | None = None
    point: str | None = None
    subpoint: str | None = None
    source: str = ""
    note: str | None = None

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())

    @property
    def reference(self) -> str:
        tail = "".join(
            filter(
                None,
                (
                    f" ч. {self.part}" if self.part else "",
                    f" п. {self.point}" if self.point else "",
                    f" подп. {self.subpoint}" if self.subpoint else "",
                ),
            )
        )
        return f"{self.act}, ст. {self.article}{tail}"


class NormIndex:
    def __init__(self, norms: list[Norm]) -> None:
        self._norms = norms

    @classmethod
    def load(cls, path: Path | None = None) -> NormIndex:
        source = path or NORMS_PATH
        if not source.is_file():
            return cls([])

        norms = []
        with source.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    norms.append(Norm(**json.loads(line)))
        return cls(norms)

    def __len__(self) -> int:
        return len(self._norms)

    @property
    def acts(self) -> set[str]:
        return {norm.act for norm in self._norms}

    def resolve(self, citation: Citation) -> list[Norm]:
        """Наиболее точное совпадение: от подпункта к статье в целом."""
        candidates = [
            norm
            for norm in self._norms
            if norm.act == citation.act and norm.article == citation.article
        ]
        if not candidates:
            return []

        parts = _expand_range(citation.part)
        points = _expand_range(citation.point)

        for narrow in (
            lambda n: n.part in parts and n.point in points and n.subpoint == citation.subpoint,
            lambda n: n.part in parts and n.point in points,
            lambda n: n.part in parts,
        ):
            matched = [norm for norm in candidates if narrow(norm)]
            if matched:
                return matched

        return candidates

    def resolve_ref(self, act: str, ref: str) -> list[Norm]:
        citation = Citation.parse(act, ref)
        if citation:
            return self.resolve(citation)

        # Ссылка вида «требует сверки редакции» не разбирается как цитата, но
        # в корпусе может быть запись о пробеле, заведённая под этим же текстом.
        return [
            norm for norm in self._norms if norm.act == act and norm.article == ref.strip()
        ]


@lru_cache
def get_norms() -> NormIndex:
    return NormIndex.load()

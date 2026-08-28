"""Разбор текста закона на нормы с точностью до части, пункта и подпункта.

Источник — выгрузки в `data/raw/laws/`, где главы и статьи размечены заголовками
уровня `###`. Каждая часть и пункт получают собственную запись, чтобы ссылку
вида «ст. 1 ч. 7 п. 1» можно было разрешить в конкретный текст.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_CHAPTER = re.compile(r"^###\s+Глава\s+([\d.]+)\.\s*(?P<title>.*)$")
_ARTICLE = re.compile(r"^###\s+Статья\s+(?P<number>[\d.\-]+?)\.\s*(?P<title>.*)$")
_PART = re.compile(r"^(?P<number>\d+)\.\s+(?P<text>\S.*)$")
_POINT = re.compile(r"^(?P<number>[\d.]+)\)\s+(?P<text>\S.*)$")
_SUBPOINT = re.compile(r"^(?P<number>[а-я])\)\s+(?P<text>\S.*)$")

# Редакторские пометки о сроках вступления, а не текст закона.
_EFFECTIVE_NOTE = re.compile(
    r"^(Часть|Части|Пункт|Пункты|Подпункт|Абзац|Статья|Глава)\b.*"
    r"(действует|действуют|вступает|вступают)\s+(в\s+силу\s+)?с\s+(?P<date>[\d.]+)"
)


@dataclass
class Provision:
    act: str
    article: str
    article_title: str
    text: str
    part: str | None = None
    point: str | None = None
    subpoint: str | None = None
    chapter: str | None = None
    effective_note: str | None = None

    @property
    def reference(self) -> str:
        parts = [f"ст. {self.article}"]
        if self.part:
            parts.append(f"ч. {self.part}")
        if self.point:
            parts.append(f"п. {self.point}")
        if self.subpoint:
            parts.append(f"подп. {self.subpoint}")
        return " ".join(parts)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "act": self.act,
            "article": self.article,
            "article_title": self.article_title,
            "part": self.part,
            "point": self.point,
            "subpoint": self.subpoint,
            "chapter": self.chapter,
            "text": self.text,
            "effective_note": self.effective_note,
        }


@dataclass
class _State:
    act: str
    chapter: str | None = None
    article: str | None = None
    article_title: str = ""
    part: str | None = None
    point: str | None = None
    pending_note: str | None = None
    provisions: list[Provision] = field(default_factory=list)

    def add(self, text: str, *, part: str | None, point: str | None, subpoint: str | None) -> None:
        if self.article is None:
            return

        self.provisions.append(
            Provision(
                act=self.act,
                article=self.article,
                article_title=self.article_title,
                text=text,
                part=part,
                point=point,
                subpoint=subpoint,
                chapter=self.chapter,
                effective_note=self.pending_note,
            )
        )
        self.pending_note = None


def parse_law(path: str | Path, act: str) -> list[Provision]:
    source = Path(path)
    state = _State(act=act)

    for raw_line in source.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        chapter = _CHAPTER.match(line)
        if chapter:
            state.chapter = f"Глава {chapter.group(1)}. {chapter.group('title')}".strip()
            continue

        article = _ARTICLE.match(line)
        if article:
            state.article = article.group("number")
            state.article_title = article.group("title").strip()
            state.part = None
            state.point = None
            continue

        if line.startswith("#"):
            continue

        note = _EFFECTIVE_NOTE.match(line)
        if note:
            state.pending_note = line
            continue

        part = _PART.match(line)
        if part:
            state.part = part.group("number")
            state.point = None
            state.add(part.group("text"), part=state.part, point=None, subpoint=None)
            continue

        point = _POINT.match(line)
        if point:
            state.point = point.group("number")
            state.add(point.group("text"), part=state.part, point=state.point, subpoint=None)
            continue

        subpoint = _SUBPOINT.match(line)
        if subpoint:
            state.add(
                subpoint.group("text"),
                part=state.part,
                point=state.point,
                subpoint=subpoint.group("number"),
            )
            continue

        # Продолжение предыдущей нормы: абзац без собственной нумерации.
        if state.provisions and state.article is not None:
            previous = state.provisions[-1]
            previous.text = f"{previous.text}\n{line}"

    return state.provisions

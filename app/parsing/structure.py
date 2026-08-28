from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.parsing.document import Document

# Многоуровневый номер («2.3», «2.3.1») распознаётся с точкой на конце и без неё.
# Одноуровневый требует точку: иначе строка «10 000 000 рублей» будет принята
# за пункт 10.
_NUMBERED = re.compile(
    r"^(?P<number>\d+(?:\.\d+)+)\.?\s+(?P<rest>\S.*)$"
    r"|^(?P<single>\d+)\.\s+(?P<single_rest>\S.*)$"
)

_UPPER_HEADING = re.compile(r"^[А-ЯЁA-Z][А-ЯЁA-Z\s,«»\"()\-–—]{4,}$")


@dataclass
class Clause:
    number: str
    level: int
    text: str
    paragraph_index: int
    heading: str | None = None
    children: list[str] = field(default_factory=list)

    @property
    def is_section(self) -> bool:
        return self.level == 1


def _parse_number(line: str) -> tuple[str, str] | None:
    match = _NUMBERED.match(line)
    if not match:
        return None

    number = match.group("number") or match.group("single")
    rest = match.group("rest") or match.group("single_rest")
    return number, rest.strip()


def split_clauses(document: Document) -> list[Clause]:
    """Разбирает документ на нумерованные пункты.

    Текст без номера присоединяется к последнему найденному пункту: в контрактах
    это продолжение абзаца, а не самостоятельное условие.
    """
    clauses: list[Clause] = []

    for index, paragraph in enumerate(document.paragraphs):
        parsed = _parse_number(paragraph)

        if parsed is None:
            if clauses:
                clauses[-1].text = f"{clauses[-1].text} {paragraph}".strip()
            continue

        number, rest = parsed
        level = number.count(".") + 1
        heading = rest if level == 1 and _UPPER_HEADING.match(rest) else None

        clauses.append(
            Clause(
                number=number,
                level=level,
                text=rest,
                paragraph_index=index,
                heading=heading,
            )
        )

    _link_children(clauses)
    return clauses


def _link_children(clauses: list[Clause]) -> None:
    by_number = {clause.number: clause for clause in clauses}

    for clause in clauses:
        if clause.level == 1:
            continue
        parent_number = clause.number.rsplit(".", 1)[0]
        parent = by_number.get(parent_number)
        if parent is not None:
            parent.children.append(clause.number)


def find_clauses(clauses: list[Clause], pattern: str) -> list[Clause]:
    """Пункты, текст которых соответствует шаблону. Используется правилами."""
    compiled = re.compile(pattern, re.IGNORECASE)
    return [clause for clause in clauses if compiled.search(clause.text)]

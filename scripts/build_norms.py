"""Сборка корпуса норм, на которые ссылается матрица правил.

Тексты 282-ФЗ берутся из выгрузки закона в `data/raw/laws` (вне git), нормы
115-ФЗ и 173-ФЗ — из выверенного вручную `config/norms_amendments.yaml`.
Результат — `data/curated/norms.jsonl`, он коммитится: тесты и заключение
работают с ним, а не с исходной выгрузкой.

    python -m scripts.build_norms
"""

from __future__ import annotations

import json
import sys

import yaml

from app.core.config import PROJECT_ROOT
from app.ingestion.laws import parse_law
from app.norms.index import Citation
from app.rules.registry import load_rules

RAW_LAWS = PROJECT_ROOT / "data" / "raw" / "laws"
AMENDMENTS = PROJECT_ROOT / "config" / "norms_amendments.yaml"
OUTPUT = PROJECT_ROOT / "data" / "curated" / "norms.jsonl"

PARSED_ACTS = {"282-ФЗ": RAW_LAWS / "282-fz-2026.md"}

FIELDS = (
    "act",
    "article",
    "article_title",
    "part",
    "point",
    "subpoint",
    "text",
    "source",
    "note",
)


def _cited_articles() -> dict[str, set[str]]:
    """Статьи, на которые ссылается матрица, по каждому акту."""
    wanted: dict[str, set[str]] = {}
    for rule in load_rules().rules:
        for ref in rule.norm_refs:
            citation = Citation.parse(ref.act, ref.ref)
            if citation:
                wanted.setdefault(citation.act, set()).add(citation.article)
    return wanted


def _from_parsed_laws(wanted: dict[str, set[str]]) -> list[dict[str, str | None]]:
    collected: list[dict[str, str | None]] = []

    for act, path in PARSED_ACTS.items():
        if not path.is_file():
            print(f"Пропущен {act}: нет файла {path}", file=sys.stderr)
            continue

        articles = wanted.get(act, set())
        for provision in parse_law(path, act):
            if provision.article not in articles:
                continue
            record = provision.to_dict()
            record["source"] = f"{act}, выгрузка {path.name}"
            record.pop("chapter", None)
            record.pop("effective_note", None)
            collected.append(record)

    return collected


def _from_amendments() -> list[dict[str, str | None]]:
    document = yaml.safe_load(AMENDMENTS.read_text(encoding="utf-8"))
    collected = []

    for entry in document["norms"]:
        record = {field: entry.get(field) for field in FIELDS}
        record["text"] = (record["text"] or "").strip()
        record["source"] = record["source"] or ""
        collected.append(record)

    return collected


def main() -> int:
    wanted = _cited_articles()
    records = _from_parsed_laws(wanted) + _from_amendments()

    if not records:
        print("Корпус пуст: нечего записывать", file=sys.stderr)
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps({k: record.get(k) for k in FIELDS}, ensure_ascii=False))
            handle.write("\n")

    by_act: dict[str, int] = {}
    for record in records:
        act = str(record["act"])
        by_act[act] = by_act.get(act, 0) + 1

    print(f"Записано норм: {len(records)} -> {OUTPUT.relative_to(PROJECT_ROOT)}")
    for act, count in sorted(by_act.items()):
        print(f"  {act}: {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

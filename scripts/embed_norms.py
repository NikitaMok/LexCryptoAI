"""Строит кэш векторов нормативного корпуса.

Нужен пакет fastembed и веса модели. Результат — data/chroma/norm_vectors.bin,
в git не входит. Пока кэш совпадает с корпусом, повторный запуск его переиспользует.

    python -m scripts.embed_norms
    python -m scripts.embed_norms --force
"""

from __future__ import annotations

import argparse
import sys

from app.norms.dense import DenseNormSearch, dense_available, get_dense
from app.norms.vectors import CACHE_NAME
from app.core.config import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Кэш векторов нормативного корпуса")
    parser.add_argument(
        "--force",
        action="store_true",
        help="пересчитать векторы, даже если кэш совпадает с корпусом",
    )
    args = parser.parse_args(argv)

    if not dense_available():
        print("fastembed не установлен", file=sys.stderr)
        return 2

    get_dense.cache_clear()
    search = DenseNormSearch.from_index(force=args.force)
    get_dense.cache_clear()

    path = get_settings().chroma_persist_dir / CACHE_NAME
    print(f"проиндексировано норм: {len(search)}")
    print(f"кэш: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

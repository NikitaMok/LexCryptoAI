"""Кэш векторов корпуса. Без numpy: файл читается и в CI.

Путь — `data/chroma/norm_vectors.bin` (каталог в git не коммитится).
Кэш привязан к модели и отпечатку текстов: смена корпуса или модели
пересобирает индекс.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from app.norms.index import Norm

MAGIC = b"LXE1"
CACHE_NAME = "norm_vectors.bin"


def corpus_fingerprint(norms: list[Norm], model_name: str) -> str:
    digest = hashlib.sha256()
    digest.update(model_name.encode("utf-8"))
    digest.update(b"\0")
    for norm in norms:
        digest.update(norm.reference.encode("utf-8"))
        digest.update(b"\0")
        digest.update(norm.text.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _write_str(handle, text: str) -> None:
    raw = text.encode("utf-8")
    handle.write(struct.pack("<I", len(raw)))
    handle.write(raw)


def _read_str(handle) -> str:
    raw = handle.read(4)
    if len(raw) != 4:
        raise ValueError("обрезанный кэш векторов")
    (length,) = struct.unpack("<I", raw)
    data = handle.read(length)
    if len(data) != length:
        raise ValueError("обрезанный кэш векторов")
    return data.decode("utf-8")


def save_vectors(
    path: Path,
    *,
    model_name: str,
    fingerprint: str,
    pairs: list[tuple[str, list[float]]],
) -> None:
    if not pairs:
        raise ValueError("нечего записывать в кэш векторов")
    dim = len(pairs[0][1])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as handle:
        handle.write(MAGIC)
        _write_str(handle, model_name)
        _write_str(handle, fingerprint)
        handle.write(struct.pack("<I", len(pairs)))
        handle.write(struct.pack("<H", dim))
        for reference, vector in pairs:
            if len(vector) != dim:
                raise ValueError(f"разная размерность у {reference}")
            _write_str(handle, reference)
            handle.write(struct.pack(f"<{dim}f", *vector))
    tmp.replace(path)


def load_vectors(
    path: Path,
    *,
    model_name: str,
    fingerprint: str,
) -> dict[str, list[float]] | None:
    if not path.is_file():
        return None
    try:
        with path.open("rb") as handle:
            magic = handle.read(len(MAGIC))
            if magic != MAGIC:
                return None
            stored_model = _read_str(handle)
            stored_fingerprint = _read_str(handle)
            if stored_model != model_name or stored_fingerprint != fingerprint:
                return None
            (count,) = struct.unpack("<I", handle.read(4))
            (dim,) = struct.unpack("<H", handle.read(2))
            vectors: dict[str, list[float]] = {}
            fmt = f"<{dim}f"
            width = struct.calcsize(fmt)
            for _ in range(count):
                reference = _read_str(handle)
                raw = handle.read(width)
                if len(raw) != width:
                    return None
                vectors[reference] = list(struct.unpack(fmt, raw))
            return vectors
    except (OSError, struct.error, ValueError, UnicodeDecodeError):
        return None

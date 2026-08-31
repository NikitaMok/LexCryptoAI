"""Каталог источников из config/providers.yaml."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from app.core.config import PROJECT_ROOT, get_settings

CATALOG_PATH = PROJECT_ROOT / "config" / "providers.yaml"


class LlmSettings(BaseModel):
    provider: str
    model: str
    base_url: str


class Source(BaseModel):
    id: str
    enabled: bool
    tier: str
    what: str = ""
    base_url: str | None = None
    env_key: str | None = None
    module: str | None = None


class Catalog(BaseModel):
    llm: LlmSettings
    wallet: list[Source] = Field(default_factory=list)
    counterparty: list[Source] = Field(default_factory=list)

    def enabled(self, group: str, *, tier: str | None = None) -> list[Source]:
        items = getattr(self, group)
        return [
            item
            for item in items
            if item.enabled and (tier is None or item.tier == tier)
        ]

    def source(self, group: str, source_id: str) -> Source | None:
        for item in getattr(self, group):
            if item.id == source_id:
                return item
        return None


def _read_catalog(path: Path) -> Catalog:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Catalog.model_validate(payload)


@lru_cache
def load_catalog(path: Path | None = None) -> Catalog:
    catalog = _read_catalog(path or CATALOG_PATH)
    settings = get_settings()
    # `.env` перекрывает yaml: так меняют модель, не трогая каталог.
    llm = catalog.llm.model_copy(
        update={
            "provider": settings.llm_provider or catalog.llm.provider,
            "model": settings.ollama_model or catalog.llm.model,
            "base_url": str(settings.ollama_base_url or catalog.llm.base_url),
        }
    )
    return catalog.model_copy(update={"llm": llm})

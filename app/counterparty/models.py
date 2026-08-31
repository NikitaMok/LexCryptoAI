"""Сверка контрагента по открытым источникам.

В сеть уходят ИНН и наименование, не текст договора.
Нет ответа источника — в отчёте «сверка не выполнена», не «всё в порядке».
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.rules.guardrail import assert_clean

NOT_PERFORMED = "сверка не выполнена"
NO_RUSSIAN_INN = (
    "российского ИНН в тексте нет; сверка по ЕГРЮЛ, Rusprofile и СБИС не выполнялась"
)
FOREIGN_NO_SOURCE = (
    "иностранный контрагент: источника по юрисдикции регистрации нет, сверка не выполнена"
)


@dataclass(frozen=True)
class SourceHit:
    source_id: str
    performed: bool
    found: bool
    legal_name: str | None = None
    inn: str | None = None
    ogrn: str | None = None
    status: str | None = None
    name_match: bool | None = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "source": self.source_id,
            "performed": self.performed,
            "found": self.found,
            "legal_name": self.legal_name,
            "inn": self.inn,
            "ogrn": self.ogrn,
            "status": self.status,
            "name_match": self.name_match,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PartyCheck:
    name: str
    inn: str | None
    foreign: bool
    hits: tuple[SourceHit, ...]
    summary: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "inn": self.inn,
            "foreign": self.foreign,
            "hits": [hit.to_dict() for hit in self.hits],
            "summary": self.summary,
        }


def _norm_name(value: str) -> str:
    text = value.lower().replace("ё", "е")
    text = re.sub(r"[«»\"'`]", "", text)
    text = re.sub(
        r"\b(ооо|ао|пао|зао|оао|нао|ип|ltd|limited|inc|gmbh|llc|co)\b\.?",
        "",
        text,
    )
    return re.sub(r"[^a-zа-я0-9]+", "", text)


def names_match(left: str, right: str) -> bool:
    a, b = _norm_name(left), _norm_name(right)
    if not a or not b:
        return False
    return a in b or b in a


def skipped(source_id: str, reason: str) -> SourceHit:
    assert_clean(reason)
    return SourceHit(source_id=source_id, performed=False, found=False, detail=reason)


def summarize(hits: tuple[SourceHit, ...], *, foreign: bool, has_inn: bool) -> str:
    if foreign and not has_inn:
        assert_clean(FOREIGN_NO_SOURCE)
        return FOREIGN_NO_SOURCE
    if not has_inn:
        assert_clean(NO_RUSSIAN_INN)
        return NO_RUSSIAN_INN
    performed = [hit for hit in hits if hit.performed]
    if not performed:
        assert_clean(NOT_PERFORMED)
        return NOT_PERFORMED
    found = [hit for hit in performed if hit.found]
    if not found:
        text = "в открытых источниках запись по ИНН не найдена"
        assert_clean(text)
        return text
    mismatch = [hit for hit in found if hit.name_match is False]
    liquidated = [
        hit
        for hit in found
        if hit.status and ("ликвидир" in hit.status.lower() or "исключ" in hit.status.lower())
    ]
    if liquidated:
        text = "по реестру организация ликвидирована либо исключена из ЕГРЮЛ"
        assert_clean(text)
        return text
    if mismatch:
        text = "запись в реестре найдена, наименование в договоре с ней не совпадает"
        assert_clean(text)
        return text
    text = "запись в открытом реестре найдена; это не подтверждение правоспособности"
    assert_clean(text)
    return text

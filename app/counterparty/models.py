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
FOREIGN_NOT_PERFORMED = "иностранный контрагент: сверка не выполнена"
FOREIGN_NOT_FOUND = (
    "в открытых иностранных реестрах запись по наименованию не найдена"
)
FOREIGN_FOUND = (
    "запись в открытом иностранном реестре найдена; это не подтверждение правоспособности"
)
FOREIGN_NAME_MISMATCH = (
    "запись в иностранном реестре найдена, наименование в договоре с ней не совпадает"
)
FOREIGN_INACTIVE = "по открытому реестру организация недействующая или исключена"


@dataclass(frozen=True)
class SourceHit:
    source_id: str
    performed: bool
    found: bool
    legal_name: str | None = None
    inn: str | None = None
    ogrn: str | None = None
    registration_number: str | None = None
    jurisdiction: str | None = None
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
            "registration_number": self.registration_number,
            "jurisdiction": self.jurisdiction,
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


def _inactive(status: str | None) -> bool:
    if not status:
        return False
    lowered = status.lower()
    markers = (
        "ликвидир",
        "исключ",
        "прекращ",
        "inactive",
        "dissolved",
        "struck",
        "revoked",
        "retired",
    )
    return any(marker in lowered for marker in markers)


def summarize(hits: tuple[SourceHit, ...], *, foreign: bool, has_inn: bool) -> str:
    if foreign:
        return _summarize_foreign(hits)
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
    liquidated = [hit for hit in found if _inactive(hit.status)]
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


def _summarize_foreign(hits: tuple[SourceHit, ...]) -> str:
    performed = [hit for hit in hits if hit.performed]
    if not performed:
        assert_clean(FOREIGN_NOT_PERFORMED)
        return FOREIGN_NOT_PERFORMED
    found = [hit for hit in performed if hit.found]
    if not found:
        assert_clean(FOREIGN_NOT_FOUND)
        return FOREIGN_NOT_FOUND
    if any(_inactive(hit.status) for hit in found):
        assert_clean(FOREIGN_INACTIVE)
        return FOREIGN_INACTIVE
    if any(hit.name_match is False for hit in found):
        assert_clean(FOREIGN_NAME_MISMATCH)
        return FOREIGN_NAME_MISMATCH
    assert_clean(FOREIGN_FOUND)
    return FOREIGN_FOUND

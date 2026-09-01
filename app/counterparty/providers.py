"""Коннекторы сверки контрагента.

Российская сторона (есть ИНН): ЕГРЮЛ ФНС, rusprofile.ru, saby.ru.
Иностранная сторона (нет российского ИНН): OpenCorporates и GLEIF, без ключа.
Платный коннектор включается записью `enabled: true` в config/providers.yaml
и ключом в `.env`. Пока HTTP-клиента нет — в отчёте «сверка не выполнена».
"""

from __future__ import annotations

import re

import httpx

from app.core.catalog import load_catalog
from app.counterparty.models import SourceHit, names_match, skipped
from app.rules.guardrail import assert_clean

_TIMEOUT = httpx.Timeout(8.0, connect=4.0)
_HEADERS = {
    "User-Agent": "LexCryptoAI/0.6 (local contract check)",
    "Accept": "application/json, text/html;q=0.8",
}

_OC_SEARCH = "https://api.opencorporates.com/v0.4/companies/search"
_GLEIF_SEARCH = "https://api.gleif.org/api/v1/lei-records"

_EGRUL_START = "https://egrul.nalog.gov.ru/"
_RUSPROFILE_SEARCH = "https://www.rusprofile.ru/search"
_SABY_CARD = "https://saby.ru/contragents/{inn}"

_BLOCK_MARKERS = (
    "smartcaptcha",
    "g-recaptcha",
    "hcaptcha",
    "cf-challenge",
    "captcha required",
    "доступ ограничен",
    "just a moment",
)


def _blocked_page(html: str, inn: str) -> bool:
    """Капча и заглушка CDN — не карточка организации."""
    lowered = html.lower()
    if inn and inn in html and ("<h1" in lowered or "огрн" in lowered or "ogrn" in lowered):
        return False
    return any(marker in lowered for marker in _BLOCK_MARKERS)


def lookup_free_sources(
    inn: str | None,
    name: str,
    client: httpx.Client | None = None,
    *,
    foreign: bool = False,
) -> tuple[SourceHit, ...]:
    catalog = load_catalog()
    hits: list[SourceHit] = []
    own = client is None
    session = client or httpx.Client(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True)
    try:
        if foreign:
            hits.extend(_lookup_foreign(name, session, catalog))
        else:
            hits.extend(_lookup_russian(inn, name, session, catalog))
    finally:
        if own:
            session.close()
    hits.extend(paid_party_notes())
    return tuple(hits)


def _lookup_russian(inn: str | None, name: str, session: httpx.Client, catalog) -> list[SourceHit]:
    hits: list[SourceHit] = []
    if catalog.uses("counterparty", "egrul"):
        hits.append(_egrul(inn, name, session) if inn else skipped("egrul", "нет ИНН"))
    if catalog.uses("counterparty", "rusprofile"):
        hits.append(
            _rusprofile(inn, name, session) if inn else skipped("rusprofile", "нет ИНН")
        )
    if catalog.uses("counterparty", "saby"):
        hits.append(_saby(inn, name, session) if inn else skipped("saby", "нет ИНН"))
    return hits


def _lookup_foreign(name: str, session: httpx.Client, catalog) -> list[SourceHit]:
    hits: list[SourceHit] = []
    query = " ".join(name.split())
    if len(query) < 4:
        if catalog.uses("counterparty", "opencorporates"):
            hits.append(skipped("opencorporates", "нет наименования иностранной стороны"))
        if catalog.uses("counterparty", "gleif"):
            hits.append(skipped("gleif", "нет наименования иностранной стороны"))
        return hits
    if catalog.uses("counterparty", "opencorporates"):
        hits.append(_opencorporates(query, session))
    if catalog.uses("counterparty", "gleif"):
        hits.append(_gleif(query, session))
    return hits


def paid_party_notes() -> tuple[SourceHit, ...]:
    catalog = load_catalog()
    notes: list[SourceHit] = []
    for source in catalog.enabled("counterparty", tier="paid"):
        if catalog.secret(source):
            notes.append(
                skipped(source.id, "коннектор не реализован, сверка не выполнена")
            )
        else:
            notes.append(skipped(source.id, "ключ не задан, сверка не выполнена"))
    return tuple(notes)


def _egrul(inn: str, name: str, session: httpx.Client) -> SourceHit:
    try:
        start = session.post(_EGRUL_START, data={"query": inn})
        start.raise_for_status()
        if _blocked_page(start.text, inn):
            return skipped("egrul", "ЕГРЮЛ не вернул результат поиска (капча или заглушка)")
        if "text/html" in start.headers.get("content-type", "") and "t" not in start.text[:200]:
            try:
                payload = start.json()
            except ValueError:
                return skipped("egrul", "ЕГРЮЛ вернул страницу вместо данных (часто капча)")
        else:
            try:
                payload = start.json()
            except ValueError:
                return skipped("egrul", "ЕГРЮЛ вернул не JSON")
        token = str(payload.get("t") or "")
        if payload.get("captchaRequired") or not token:
            return skipped("egrul", "ЕГРЮЛ не вернул результат поиска")
        result = session.get(f"{_EGRUL_START}search-result/{token}")
        result.raise_for_status()
        body = result.json()
        rows = body.get("rows") or body.get("items") or []
        if not isinstance(rows, list) or not rows:
            detail = "в ЕГРЮЛ запись по ИНН не найдена"
            assert_clean(detail)
            return SourceHit(
                source_id="egrul",
                performed=True,
                found=False,
                inn=inn,
                detail=detail,
            )
        row = next((item for item in rows if str(item.get("i") or "") == inn), rows[0])
        legal = str(row.get("n") or row.get("c") or "").strip()
        ogrn = str(row.get("o") or row.get("k") or "").strip() or None
        ended = str(row.get("e") or "").strip()
        status = "прекращена" if ended else "действует"
        match = names_match(name, legal) if name and legal else None
        detail = f"ЕГРЮЛ: {legal or 'наименование не разобрано'}, статус: {status}"
        assert_clean(detail)
        return SourceHit(
            source_id="egrul",
            performed=True,
            found=True,
            legal_name=legal or None,
            inn=str(row.get("i") or inn),
            ogrn=ogrn,
            status=status,
            name_match=match,
            detail=detail,
        )
    except httpx.TimeoutException:
        return skipped("egrul", "таймаут запроса, сверка не выполнена")
    except httpx.HTTPStatusError as error:
        return skipped(
            "egrul",
            f"ЕГРЮЛ ответил отказом (HTTP {error.response.status_code}), сверка не выполнена",
        )
    except httpx.HTTPError as error:
        return skipped("egrul", f"ЕГРЮЛ недоступен: {error.__class__.__name__}")
    except ValueError:
        return skipped("egrul", "ЕГРЮЛ вернул неразборчивый ответ")


def _html_status(html: str) -> str | None:
    lowered = html.lower()
    if "ликвидир" in lowered:
        return "ликвидирована"
    if "исключен" in lowered or "исключён" in lowered:
        return "исключена из реестра"
    if "действующ" in lowered:
        return "действует"
    return None


def _html_title(html: str) -> str:
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    raw = match.group(1) if match else ""
    if not raw:
        title = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        raw = title.group(1) if title else ""
    return re.sub(r"<[^>]+>", "", raw)


def _page_hit(source_id: str, inn: str, name: str, html: str) -> SourceHit:
    if inn not in html:
        detail = f"{source_id}: страница не содержит запрошенный ИНН"
        assert_clean(detail)
        return SourceHit(
            source_id=source_id,
            performed=True,
            found=False,
            inn=inn,
            detail=detail,
        )
    title = " ".join(_html_title(html).split())
    legal = title.split("—")[0].split("|")[0].strip() if title else None
    status = _html_status(html)
    match = names_match(name, legal) if name and legal else None
    bits = [source_id]
    if legal:
        bits.append(legal)
    if status:
        bits.append(status)
    detail = ": ".join(bits) if len(bits) > 1 else f"{source_id}: страница открыта"
    assert_clean(detail)
    return SourceHit(
        source_id=source_id,
        performed=True,
        found=True,
        legal_name=legal or None,
        inn=inn,
        status=status,
        name_match=match,
        detail=detail,
    )


def _rusprofile(inn: str, name: str, session: httpx.Client) -> SourceHit:
    try:
        response = session.get(_RUSPROFILE_SEARCH, params={"query": inn})
        response.raise_for_status()
        if _blocked_page(response.text, inn):
            return skipped("rusprofile", "Rusprofile вернул капчу или заглушку, сверка не выполнена")
        return _page_hit("rusprofile", inn, name, response.text)
    except httpx.TimeoutException:
        return skipped("rusprofile", "таймаут запроса, сверка не выполнена")
    except httpx.HTTPStatusError as error:
        return skipped(
            "rusprofile",
            f"Rusprofile ответил отказом (HTTP {error.response.status_code}), сверка не выполнена",
        )
    except httpx.HTTPError as error:
        return skipped("rusprofile", f"Rusprofile недоступен: {error.__class__.__name__}")


def _saby(inn: str, name: str, session: httpx.Client) -> SourceHit:
    try:
        response = session.get(_SABY_CARD.format(inn=inn))
        response.raise_for_status()
        if _blocked_page(response.text, inn):
            return skipped("saby", "СБИС вернул капчу или заглушку, сверка не выполнена")
        return _page_hit("saby", inn, name, response.text)
    except httpx.TimeoutException:
        return skipped("saby", "таймаут запроса, сверка не выполнена")
    except httpx.HTTPStatusError as error:
        return skipped(
            "saby",
            f"СБИС ответил отказом (HTTP {error.response.status_code}), сверка не выполнена",
        )
    except httpx.HTTPError as error:
        return skipped("saby", f"СБИС недоступен: {error.__class__.__name__}")


def _opencorporates(name: str, session: httpx.Client) -> SourceHit:
    catalog = load_catalog()
    source = catalog.source("counterparty", "opencorporates")
    params: dict[str, str | int] = {"q": name, "per_page": 5}
    token = catalog.secret(source) if source else ""
    if token:
        params["api_token"] = token
    try:
        response = session.get(_OC_SEARCH, params=params)
        response.raise_for_status()
        payload = response.json()
        rows = ((payload.get("results") or {}).get("companies")) or []
        if not isinstance(rows, list) or not rows:
            detail = "OpenCorporates: по наименованию записей нет"
            assert_clean(detail)
            return SourceHit(
                source_id="opencorporates",
                performed=True,
                found=False,
                legal_name=None,
                detail=detail,
            )
        picked = _pick_company_row(name, rows, key="company")
        if picked is None:
            detail = "OpenCorporates: однозначной записи по наименованию нет"
            assert_clean(detail)
            return SourceHit(
                source_id="opencorporates",
                performed=True,
                found=False,
                detail=detail,
            )
        legal = str(picked.get("name") or "").strip()
        number = str(picked.get("company_number") or "").strip() or None
        jurisdiction = str(picked.get("jurisdiction_code") or "").strip() or None
        inactive = bool(picked.get("inactive"))
        status = str(picked.get("current_status") or "").strip() or (
            "inactive" if inactive else "active"
        )
        match = names_match(name, legal) if name and legal else None
        bits = ["OpenCorporates", legal or "наименование не разобрано"]
        if jurisdiction:
            bits.append(jurisdiction)
        if number:
            bits.append(f"номер {number}")
        bits.append(status)
        detail = ": ".join(bits[:2]) + (", " + ", ".join(bits[2:]) if len(bits) > 2 else "")
        assert_clean(detail)
        return SourceHit(
            source_id="opencorporates",
            performed=True,
            found=True,
            legal_name=legal or None,
            registration_number=number,
            jurisdiction=jurisdiction,
            status=status,
            name_match=match,
            detail=detail,
        )
    except httpx.TimeoutException:
        return skipped("opencorporates", "таймаут запроса, сверка не выполнена")
    except httpx.HTTPStatusError as error:
        return skipped(
            "opencorporates",
            f"OpenCorporates ответил отказом (HTTP {error.response.status_code}), "
            "сверка не выполнена",
        )
    except httpx.HTTPError as error:
        return skipped("opencorporates", f"OpenCorporates недоступен: {error.__class__.__name__}")
    except (ValueError, TypeError):
        return skipped("opencorporates", "OpenCorporates вернул неразборчивый ответ")


def _gleif(name: str, session: httpx.Client) -> SourceHit:
    try:
        response = session.get(
            _GLEIF_SEARCH,
            params={"filter[entity.legalName]": name, "page[size]": 5},
            headers={"Accept": "application/vnd.api+json"},
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") or []
        if not isinstance(rows, list) or not rows:
            detail = "GLEIF: по наименованию записей LEI нет"
            assert_clean(detail)
            return SourceHit(
                source_id="gleif",
                performed=True,
                found=False,
                detail=detail,
            )
        chosen: dict | None = None
        legal = ""
        for item in rows:
            if not isinstance(item, dict):
                continue
            entity = ((item.get("attributes") or {}).get("entity")) or {}
            name_block = entity.get("legalName") or {}
            candidate = str(
                name_block.get("name") if isinstance(name_block, dict) else name_block or ""
            ).strip()
            if candidate and names_match(name, candidate):
                chosen = item
                legal = candidate
                break
        if chosen is None:
            detail = "GLEIF: однозначной записи LEI по наименованию нет"
            assert_clean(detail)
            return SourceHit(
                source_id="gleif",
                performed=True,
                found=False,
                detail=detail,
            )
        entity = ((chosen.get("attributes") or {}).get("entity")) or {}
        lei = str((chosen.get("attributes") or {}).get("lei") or chosen.get("id") or "").strip()
        status = str(entity.get("status") or "").strip() or None
        address = entity.get("legalAddress") or {}
        country = ""
        if isinstance(address, dict):
            country = str(address.get("country") or "").strip()
        match = names_match(name, legal) if name and legal else None
        bits = ["GLEIF", legal or "наименование не разобрано"]
        if lei:
            bits.append(f"LEI {lei}")
        if country:
            bits.append(country)
        if status:
            bits.append(status)
        detail = ": ".join(bits[:2]) + (", " + ", ".join(bits[2:]) if len(bits) > 2 else "")
        assert_clean(detail)
        return SourceHit(
            source_id="gleif",
            performed=True,
            found=True,
            legal_name=legal or None,
            registration_number=lei or None,
            jurisdiction=country or None,
            status=status,
            name_match=match,
            detail=detail,
        )
    except httpx.TimeoutException:
        return skipped("gleif", "таймаут запроса, сверка не выполнена")
    except httpx.HTTPStatusError as error:
        return skipped(
            "gleif",
            f"GLEIF ответил отказом (HTTP {error.response.status_code}), сверка не выполнена",
        )
    except httpx.HTTPError as error:
        return skipped("gleif", f"GLEIF недоступен: {error.__class__.__name__}")
    except (ValueError, TypeError):
        return skipped("gleif", "GLEIF вернул неразборчивый ответ")


def _pick_company_row(name: str, rows: list, *, key: str) -> dict | None:
    matched: list[dict] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        row = item.get(key) if key in item else item
        if not isinstance(row, dict):
            continue
        legal = str(row.get("name") or "").strip()
        if legal and names_match(name, legal):
            matched.append(row)
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        return matched[0]
    return None


"""Запросы к публичным API блокчейна.

Какие источники включены — `config/providers.yaml`.
Без ключа TronGrid отвечает с лимитом; Etherscan без ключа не вызывается.
GoPlus отдаёт публичные метки риска. Платные коннекторы, если включены
в yaml без реализации, в отчёте дают «оценка не выполнена», а не «чисто».
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from app.aml.score import AddressSnapshot
from app.core.catalog import load_catalog
from app.core.config import get_settings
from app.parsing.extract import WalletAddress

_TIMEOUT = httpx.Timeout(8.0, connect=4.0)

_GOPLUS_FLAGS = {
    "phishing_activities": "фишинг",
    "blackmail_activities": "вымогательство",
    "stealing_attack": "хищение",
    "fake_kyc": "поддельный KYC",
    "malicious_mining_activities": "вредоносный майнинг",
    "darkweb_transactions": "даркнет",
    "cybercrime": "киберпреступление",
    "money_laundering": "отмывание",
    "financial_crime": "финансовое преступление",
    "mixer": "миксер",
    "sanctioned": "санкции",
    "honeypot_related_address": "honeypot",
    "gas_abuse": "злоупотребление gas",
    "reinit": "повторная инициализация контракта",
    "fake_token": "поддельный токен",
}

_CHAIN_ID = {"EVM": "1", "TRON": "tron"}


def fetch_snapshot(address: WalletAddress, client: httpx.Client | None = None) -> AddressSnapshot:
    catalog = load_catalog()
    if address.network == "TRON":
        if not catalog.uses("wallet", "trongrid"):
            snapshot = AddressSnapshot(
                address=address.value,
                network="TRON",
                error="TronGrid выключен в каталоге",
            )
        else:
            snapshot = _tron(address.value, client)
    elif address.network == "EVM":
        if not catalog.uses("wallet", "etherscan"):
            snapshot = AddressSnapshot(
                address=address.value,
                network="EVM",
                error="Etherscan выключен в каталоге",
            )
        else:
            snapshot = _evm(address.value, client)
    else:
        snapshot = AddressSnapshot(
            address=address.value,
            network=address.network,
            error=f"сеть {address.network} не поддерживается",
        )

    if catalog.uses("wallet", "goplus"):
        snapshot = _with_goplus(snapshot, address, client)
    return snapshot


def fetch_snapshots(
    addresses: list[WalletAddress],
    client: httpx.Client | None = None,
) -> list[AddressSnapshot]:
    own_client = client is None
    session = client or httpx.Client(timeout=_TIMEOUT)
    try:
        return [fetch_snapshot(address, session) for address in addresses]
    finally:
        if own_client:
            session.close()


def paid_wallet_notes() -> tuple[str, ...]:
    """Честный статус платных скорингов: включены, но коннектора нет."""
    catalog = load_catalog()
    notes: list[str] = []
    for source in catalog.enabled("wallet", tier="paid"):
        if catalog.secret(source):
            notes.append(f"{source.id}: коннектор не реализован, оценка не выполнена")
        else:
            notes.append(f"{source.id}: ключ не задан, оценка не выполнена")
    return tuple(notes)


def _with_goplus(
    snapshot: AddressSnapshot,
    address: WalletAddress,
    client: httpx.Client | None,
) -> AddressSnapshot:
    labels, error = _goplus(address, client)
    if error and snapshot.error:
        combined = f"{snapshot.error}; {error}"
        return replace(snapshot, error=combined, risk_labels=labels)
    if error and not snapshot.risk_labels and snapshot.error is None:
        # Цепочка ответила, метки нет — это не ломает возраст и баланс.
        return replace(snapshot, risk_labels=labels)
    return replace(snapshot, risk_labels=labels)


def _goplus(
    address: WalletAddress,
    client: httpx.Client | None,
) -> tuple[tuple[str, ...], str | None]:
    chain = _CHAIN_ID.get(address.network)
    if chain is None:
        return (), f"GoPlus: сеть {address.network} не поддерживается"
    session = client or httpx.Client(timeout=_TIMEOUT)
    try:
        response = session.get(
            f"https://api.gopluslabs.io/api/v1/address_security/{chain}",
            params={"address": address.value},
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("result")
        if not isinstance(result, dict):
            message = str(payload.get("message") or "нет данных")
            return (), f"GoPlus: {message[:200]}"
        labels = tuple(
            title
            for key, title in _GOPLUS_FLAGS.items()
            if str(result.get(key) or "") == "1"
        )
        return labels, None
    except httpx.HTTPError as error:
        return (), f"GoPlus недоступен: {error.__class__.__name__}"
    finally:
        if client is None:
            session.close()


def _tron(address: str, client: httpx.Client | None) -> AddressSnapshot:
    settings = get_settings()
    headers = {}
    if settings.trongrid_api_key:
        headers["TRON-PRO-API-KEY"] = settings.trongrid_api_key
    session = client or httpx.Client(timeout=_TIMEOUT)
    try:
        account = session.get(
            f"https://api.trongrid.io/v1/accounts/{address}",
            headers=headers,
        )
        account.raise_for_status()
        payload = account.json()
        rows = payload.get("data") or []
        if not rows:
            return AddressSnapshot(address=address, network="TRON", tx_count=0)

        row = rows[0]
        created = row.get("create_time")
        created_at = (
            datetime.fromtimestamp(created / 1000, tz=timezone.utc)
            if isinstance(created, (int, float)) and created > 0
            else None
        )
        usdt = _tron_usdt(row)
        tx_count = _tron_tx_count(session, address, headers)
        return AddressSnapshot(
            address=address,
            network="TRON",
            created_at=created_at,
            tx_count=tx_count,
            usdt_balance=usdt,
        )
    except httpx.HTTPError as error:
        return AddressSnapshot(
            address=address,
            network="TRON",
            error=f"TronGrid недоступен: {error.__class__.__name__}",
        )
    finally:
        if client is None:
            session.close()


def _tron_usdt(row: dict) -> Decimal | None:
    tokens = row.get("trc20") or []
    for item in tokens:
        if not isinstance(item, dict):
            continue
        for symbol, amount in item.items():
            if "USDT" in str(symbol).upper():
                try:
                    return Decimal(str(amount)) / Decimal(1_000_000)
                except Exception:
                    return None
    return Decimal(0)


def _tron_tx_count(session: httpx.Client, address: str, headers: dict) -> int | None:
    try:
        response = session.get(
            f"https://api.trongrid.io/v1/accounts/{address}/transactions",
            params={"limit": 1, "only_confirmed": "true"},
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or []
        if not data:
            return 0
        return None
    except httpx.HTTPError:
        return None


def _evm(address: str, client: httpx.Client | None) -> AddressSnapshot:
    settings = get_settings()
    if not settings.etherscan_api_key:
        return AddressSnapshot(
            address=address,
            network="EVM",
            error="ключ Etherscan не задан",
        )
    session = client or httpx.Client(timeout=_TIMEOUT)
    try:
        response = session.get(
            "https://api.etherscan.io/api",
            params={
                "module": "account",
                "action": "txlist",
                "address": address,
                "startblock": 0,
                "endblock": 99999999,
                "page": 1,
                "offset": 1,
                "sort": "asc",
                "apikey": settings.etherscan_api_key,
            },
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("result")
        if payload.get("status") != "1" or not isinstance(result, list):
            message = str(payload.get("message") or payload.get("result") or "нет данных")
            if "No transactions found" in message:
                return AddressSnapshot(address=address, network="EVM", tx_count=0)
            return AddressSnapshot(address=address, network="EVM", error=message[:200])

        first = result[0] if result else None
        created_at = None
        if first and first.get("timeStamp"):
            created_at = datetime.fromtimestamp(int(first["timeStamp"]), tz=timezone.utc)
        tx_count = len(result) if result else 0
        return AddressSnapshot(
            address=address,
            network="EVM",
            created_at=created_at,
            tx_count=tx_count,
        )
    except httpx.HTTPError as error:
        return AddressSnapshot(
            address=address,
            network="EVM",
            error=f"Etherscan недоступен: {error.__class__.__name__}",
        )
    finally:
        if client is None:
            session.close()

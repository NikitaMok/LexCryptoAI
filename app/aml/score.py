"""Предварительная оценка адреса по открытым данным.

Это не цифровой анализ в смысле статьи 35 № 282-ФЗ: нет присвоения уровня
риска сделке, нет включения в реестр поставщиков таких услуг. Оценка нужна
стороне внешнеторгового договора, чтобы увидеть, что публичный адрес
выглядит пустым, только что созданным или, наоборот, сверхнагруженным.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from app.rules.guardrail import assert_clean

DISCLAIMER = (
    "Предварительная оценка по открытым данным блокчейна. "
    "Не является цифровым анализом в смысле статьи 35 Федерального закона "
    "от 04.08.2026 № 282-ФЗ."
)

assert_clean(DISCLAIMER)

BAND_LOW = "низкий"
BAND_ELEVATED = "повышенный"
BAND_HIGH = "высокий"


@dataclass(frozen=True)
class AddressSnapshot:
    address: str
    network: str
    created_at: datetime | None = None
    tx_count: int | None = None
    usdt_balance: Decimal | None = None
    risk_labels: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class AddressScore:
    address: str
    network: str
    score: int | None
    band: str
    factors: tuple[str, ...]
    labels: tuple[str, ...] = ()
    disclaimer: str = DISCLAIMER
    error: str | None = None
    source_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "address": self.address,
            "network": self.network,
            "score": self.score,
            "band": self.band,
            "factors": list(self.factors),
            "labels": list(self.labels),
            "disclaimer": self.disclaimer,
            "error": self.error,
            "source_notes": list(self.source_notes),
        }


def _age_days(created_at: datetime, now: datetime) -> int:
    start = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return max(0, (current - start).days)


def score_snapshot(
    snapshot: AddressSnapshot,
    *,
    threshold: int = 50,
    now: datetime | None = None,
) -> AddressScore:
    if snapshot.error:
        return AddressScore(
            address=snapshot.address,
            network=snapshot.network,
            score=None,
            band="нет данных",
            factors=(),
            labels=snapshot.risk_labels,
            error=snapshot.error,
        )

    points = 0
    factors: list[str] = []
    moment = now or datetime.now(timezone.utc)

    if snapshot.created_at is None and snapshot.tx_count is None:
        points += 30
        factors.append("нет сведений об истории адреса")
    elif snapshot.created_at is not None:
        age = _age_days(snapshot.created_at, moment)
        if age < 30:
            points += 25
            factors.append(f"адрес создан {age} дн. назад")
        elif age < 90:
            points += 15
            factors.append(f"адрес создан {age} дн. назад")

    if snapshot.tx_count is not None:
        if snapshot.tx_count == 0:
            points += 20
            factors.append("транзакций не найдено")
        elif snapshot.tx_count < 5:
            points += 15
            factors.append(f"транзакций: {snapshot.tx_count}")
        elif snapshot.tx_count > 10_000:
            points += 10
            factors.append(f"очень высокая активность: {snapshot.tx_count} транзакций")

    if snapshot.usdt_balance is not None and snapshot.usdt_balance == 0:
        points += 10
        factors.append("нулевой баланс USDT")

    if snapshot.risk_labels:
        points += 40
        if any(
            label in snapshot.risk_labels
            for label in ("санкции", "миксер", "фишинг", "отмывание", "киберпреступление")
        ):
            points += 20
        factors.append("публичные метки риска: " + ", ".join(snapshot.risk_labels))

    score = min(100, points)
    if score >= threshold:
        band = BAND_HIGH
    elif score >= max(20, threshold * 3 // 5):
        band = BAND_ELEVATED
    else:
        band = BAND_LOW
        if not factors:
            factors.append("публичная история не показывает явных признаков риска")

    for fragment in factors:
        assert_clean(fragment)

    return AddressScore(
        address=snapshot.address,
        network=snapshot.network,
        score=score,
        band=band,
        factors=tuple(factors),
        labels=snapshot.risk_labels,
    )

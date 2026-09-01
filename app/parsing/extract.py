from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

# Адреса кошельков. Наличие «сырого» адреса вместо адреса-идентификатора
# цифрового депозитария — нарушение правила ADR-001.
_TRON_ADDRESS = re.compile(r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b")
_EVM_ADDRESS = re.compile(r"\b0x[a-fA-F0-9]{40}\b")

_TICKERS = {
    "USDT": ("usdt", "tether"),
    "USDC": ("usdc",),
    "DAI": ("dai",),
    "BTC": ("btc", "bitcoin", "биткойн", "биткоин"),
    "ETH": ("eth", "ethereum", "эфир"),
}

_NETWORKS = {
    "TRC-20": ("trc-20", "trc20", "tron", "трон"),
    "ERC-20": ("erc-20", "erc20", "ethereum", "эфириум"),
    "BEP-20": ("bep-20", "bep20", "bsc", "binance smart chain"),
    "TON": ("ton", "the open network"),
}

_MULTIPLIERS = {
    "тыс": Decimal(1_000),
    "тысяч": Decimal(1_000),
    "млн": Decimal(1_000_000),
    "миллион": Decimal(1_000_000),
    "млрд": Decimal(1_000_000_000),
}

_CURRENCIES = {
    "RUB": ("руб", "рубл", "rub", "₽"),
    "USD": ("долл", "usd", "$"),
    "EUR": ("евро", "eur", "€"),
    "CNY": ("юан", "cny", "юаней"),
}

# Тикеры стоят перед фиатными обозначениями, иначе из «USDT» альтернатива «USD»
# отхватит только начало. Замыкающий lookahead не даёт совпасть с префиксом.
_AMOUNT = re.compile(
    r"(?P<number>\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"\s*(?:\([^)]*\)\s*)?"
    r"(?P<multiplier>тыс(?:\.|яч[а-я]*)?|млн\.?|миллион[а-я]*|млрд\.?)?\s*"
    r"(?P<currency>USDT|USDC|DAI|BTC|ETH"
    r"|рубл[а-я]*|руб\.?|RUB|₽|долл[а-я.]*|USD|\$|евро|EUR|€|юан[а-я]*|CNY)"
    r"(?![A-Za-zА-Яа-яЁё])",
    re.IGNORECASE,
)

_INN = re.compile(r"ИНН[\s:№]*(\d{10}|\d{12})\b", re.IGNORECASE)
_RU_ORG = re.compile(
    r"(?:ООО|АО|ПАО|НАО|ЗАО|ОАО|ИП)\s+[«\"'][^»\"']{2,160}[»\"']",
    re.IGNORECASE,
)
_EN_ORG = re.compile(
    r"\b[A-Z][A-Za-z0-9&.,' \-]{2,80}"
    r"(?:Co\.,?\s*Ltd\.?|Pte\.?\s*Ltd\.?|Ltd\.|Limited|Inc\.|GmbH|LLC|Corp\.)\b"
)

_FOREIGN_TRADE = re.compile(r"внешнеторгов\w*", re.IGNORECASE)
_RESIDENT = re.compile(r"\bрезидент\w*", re.IGNORECASE)
_NON_RESIDENT = re.compile(r"\bнерезидент\w*", re.IGNORECASE)
_IDENTIFIER_ADDRESS = re.compile(r"адрес\w*[\s-]*идентификатор\w*", re.IGNORECASE)
_DEPOSITARY = re.compile(r"цифров\w*\s+депозитари\w*", re.IGNORECASE)
_RECORD_MOMENT = re.compile(r"внесени\w*\s+запис\w*", re.IGNORECASE)


@dataclass(frozen=True)
class WalletAddress:
    value: str
    network: str

    def __str__(self) -> str:
        return f"{self.value} ({self.network})"


@dataclass(frozen=True)
class PartyMention:
    name: str
    inn: str | None = None


@dataclass(frozen=True)
class MoneyAmount:
    value: Decimal
    currency: str
    raw: str


@dataclass
class ExtractedFacts:
    wallet_addresses: list[WalletAddress] = field(default_factory=list)
    tickers: list[str] = field(default_factory=list)
    networks: list[str] = field(default_factory=list)
    amounts: list[MoneyAmount] = field(default_factory=list)
    inns: list[str] = field(default_factory=list)
    parties: list[PartyMention] = field(default_factory=list)
    mentions_foreign_trade: bool = False
    mentions_resident: bool = False
    mentions_non_resident: bool = False
    mentions_identifier_address: bool = False
    mentions_depositary: bool = False
    mentions_record_moment: bool = False

    def max_amount(self, currency: str = "RUB") -> Decimal | None:
        values = [amount.value for amount in self.amounts if amount.currency == currency]
        return max(values) if values else None


def _normalize_currency(token: str) -> str:
    lowered = token.lower().rstrip(".")
    if lowered.upper() in _TICKERS:
        return lowered.upper()
    for code, variants in _CURRENCIES.items():
        if any(lowered.startswith(variant) for variant in variants):
            return code
    return token.upper()


def _normalize_multiplier(token: str | None) -> Decimal:
    if not token:
        return Decimal(1)
    lowered = token.lower().rstrip(".")
    for prefix, factor in _MULTIPLIERS.items():
        if lowered.startswith(prefix):
            return factor
    return Decimal(1)


def extract_amounts(text: str) -> list[MoneyAmount]:
    amounts: list[MoneyAmount] = []

    for match in _AMOUNT.finditer(text):
        digits = match.group("number").replace("\u00a0", "").replace(" ", "").replace(",", ".")
        value = Decimal(digits) * _normalize_multiplier(match.group("multiplier"))
        amounts.append(
            MoneyAmount(
                value=value,
                currency=_normalize_currency(match.group("currency")),
                raw=match.group(0).strip(),
            )
        )

    return amounts


def extract_wallet_addresses(text: str) -> list[WalletAddress]:
    addresses = [
        WalletAddress(value=match.group(0), network="TRON")
        for match in _TRON_ADDRESS.finditer(text)
    ]
    addresses.extend(
        WalletAddress(value=match.group(0), network="EVM")
        for match in _EVM_ADDRESS.finditer(text)
    )
    return addresses


def _find_known(text: str, catalogue: dict[str, tuple[str, ...]]) -> list[str]:
    lowered = text.lower()
    return [
        code
        for code, variants in catalogue.items()
        if any(re.search(rf"\b{re.escape(variant)}\b", lowered) for variant in variants)
    ]


def extract_party_mentions(text: str) -> list[PartyMention]:
    names: list[str] = []
    for match in _RU_ORG.finditer(text):
        names.append(" ".join(match.group(0).split()))
    for match in _EN_ORG.finditer(text):
        names.append(" ".join(match.group(0).split()))

    inns = [match.group(1) for match in _INN.finditer(text)]
    parties: list[PartyMention] = []
    used_inns: set[str] = set()

    for name in names:
        linked: str | None = None
        pos = text.find(name)
        window = text[max(0, pos - 80) : pos + len(name) + 120] if pos >= 0 else ""
        for inn in inns:
            if inn in window:
                linked = inn
                used_inns.add(inn)
                break
        parties.append(PartyMention(name=name, inn=linked))

    for inn in inns:
        if inn not in used_inns:
            parties.append(PartyMention(name="", inn=inn))
    return parties


def extract_facts(text: str) -> ExtractedFacts:
    return ExtractedFacts(
        wallet_addresses=extract_wallet_addresses(text),
        tickers=_find_known(text, _TICKERS),
        networks=_find_known(text, _NETWORKS),
        amounts=extract_amounts(text),
        inns=[match.group(1) for match in _INN.finditer(text)],
        parties=extract_party_mentions(text),
        mentions_foreign_trade=bool(_FOREIGN_TRADE.search(text)),
        mentions_resident=bool(_RESIDENT.search(text)),
        mentions_non_resident=bool(_NON_RESIDENT.search(text)),
        mentions_identifier_address=bool(_IDENTIFIER_ADDRESS.search(text)),
        mentions_depositary=bool(_DEPOSITARY.search(text)),
        mentions_record_moment=bool(_RECORD_MOMENT.search(text)),
    )

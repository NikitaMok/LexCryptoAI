"""Сверка контрагента по открытым и платным источникам.

Какие площадки вызываются, задаёт `config/providers.yaml`.
Ключи платных API — только в `.env`, не в yaml.
"""

from app.counterparty.service import review_counterparties

__all__ = ["review_counterparties"]

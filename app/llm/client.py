"""HTTP-клиент к локальной Ollama. Текст договора на эту машину не покидает."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.catalog import load_catalog
from app.core.config import get_settings

_TAGS_TIMEOUT = httpx.Timeout(2.0, connect=1.0)


@dataclass(frozen=True)
class LlmReply:
    text: str
    model: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text.strip())


def ollama_reachable(base_url: str | None = None) -> bool:
    url = (base_url or load_catalog().llm.base_url).rstrip("/") + "/api/tags"
    try:
        response = httpx.get(url, timeout=_TAGS_TIMEOUT)
        return response.status_code < 500
    except httpx.HTTPError:
        return False


def complete(prompt: str, *, client: httpx.Client | None = None) -> LlmReply:
    catalog = load_catalog()
    settings = get_settings()
    model = catalog.llm.model
    base = catalog.llm.base_url.rstrip("/")
    timeout = httpx.Timeout(settings.ollama_timeout_s, connect=5.0)
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {"temperature": settings.llm_temperature},
        "messages": [
            {
                "role": "system",
                "content": (
                    "Отвечай только JSON. Не ссылайся на статьи закона. "
                    "Не давай правовой вердикт. Не предлагай, как обойти требование."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }

    own = client is None
    session = client or httpx.Client(timeout=timeout)
    try:
        response = session.post(f"{base}/api/chat", json=payload)
        response.raise_for_status()
        body = response.json()
        text = ""
        message = body.get("message") or {}
        if isinstance(message, dict):
            text = str(message.get("content") or "")
        if not text:
            text = str(body.get("response") or "")
        if not text.strip():
            return LlmReply(text="", model=model, error="модель вернула пустой ответ")
        return LlmReply(text=text, model=model)
    except httpx.ConnectError:
        return LlmReply(text="", model=model, error="Ollama недоступна")
    except httpx.TimeoutException:
        return LlmReply(text="", model=model, error="Ollama не ответила за отведённое время")
    except httpx.HTTPError as error:
        return LlmReply(text="", model=model, error=f"Ollama: {error.__class__.__name__}")
    except ValueError:
        return LlmReply(text="", model=model, error="Ollama вернула не JSON")
    finally:
        if own:
            session.close()

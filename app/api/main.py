from fastapi import FastAPI

from app.core.config import get_settings

app = FastAPI(
    title="LexCryptoAI",
    description=(
        "Проверка внешнеторговых контрактов с расчётами в цифровой валюте "
        "на соответствие ФЗ № 282-ФЗ, 283-ФЗ и 115-ФЗ"
    ),
    version="0.1.0",
)


@app.get("/health")
async def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "env": settings.app_env, "version": app.version}

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    llm_provider: str = "ollama"
    llm_temperature: float = 0.0
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.3:70b"

    database_url: str = "postgresql+psycopg://lexcrypto:@localhost:5432/lexcrypto"

    chroma_persist_dir: Path = PROJECT_ROOT / "data" / "chroma"
    chroma_collection: str = "legal_norms"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    dense_search: bool = False

    aml_risk_threshold: int = 50
    trongrid_api_key: str = ""
    etherscan_api_key: str = ""
    hitl_confidence_threshold: float = 0.8

    upload_tmp_dir: Path = PROJECT_ROOT / "tmp" / "uploads"
    max_upload_mb: int = 20

    sentry_dsn: str = ""
    metrics_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()

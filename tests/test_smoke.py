from fastapi.testclient import TestClient

from app.api.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["dense"] == "off"
    assert response.json()["ollama"] in {"on", "off"}


def test_settings_defaults_are_loadable():
    from app.core.config import get_settings

    settings = get_settings()

    assert settings.aml_risk_threshold > 0
    assert settings.ollama_timeout_s >= 60
    assert settings.ollama_model

from fastapi.testclient import TestClient

from app.api.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_settings_defaults_are_loadable():
    from app.core.config import get_settings

    settings = get_settings()

    assert settings.aml_risk_threshold > 0
    assert 0 < settings.hitl_confidence_threshold <= 1

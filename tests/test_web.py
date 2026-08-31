from fastapi.testclient import TestClient

from app.api.main import app

client = TestClient(app)


def test_home_page_is_served():
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "282-ФЗ" in body
    assert "цифровым анализом" in body
    assert "юридическая консультация" in body
    assert "name=\"aml\"" not in body


def test_stylesheet_is_served():
    response = client.get("/static/app.css")

    assert response.status_code == 200
    assert "font-family" in response.text

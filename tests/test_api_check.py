from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import app
from app.core.config import get_settings

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("UPLOAD_TMP_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    return TestClient(app)


def _post_check(client: TestClient, path: Path, params: dict | None = None, url: str = "/check"):
    return client.post(
        url,
        files={"file": (path.name, path.read_bytes(), DOCX_TYPE)},
        params=params or {"on": "2026-09-01"},
    )


class TestCheckEndpoint:
    def test_compliant_contract_is_green(self, compliant_docx: Path, tmp_path, monkeypatch):
        response = _post_check(_client(tmp_path, monkeypatch), compliant_docx)

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "green"
        assert payload["source"] == compliant_docx.name
        assert payload["counts"]["total"] == 32
        assert payload["blocking"] == []
        assert "text" not in payload

    def test_violating_contract_is_red(self, violating_docx: Path, tmp_path, monkeypatch):
        response = _post_check(_client(tmp_path, monkeypatch), violating_docx)

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "red"
        codes = {item["code"] for item in payload["blocking"]}
        assert "ADR-001" in codes
        adr = next(item for item in payload["blocking"] if item["code"] == "ADR-001")
        assert "2.3" in adr["clauses"]

    def test_quote_norms_includes_verbatim_text(
        self, violating_docx: Path, tmp_path, monkeypatch
    ):
        response = _post_check(
            _client(tmp_path, monkeypatch),
            violating_docx,
            {"on": "2026-09-01", "quote_norms": "true"},
        )
        payload = response.json()
        ftc = next(item for item in payload["blocking"] if item["code"] == "FTC-001")
        quoted = " ".join(
            (item["text"] or item["note"] or "") for item in ftc["quoted_norms"]
        )

        assert "по внешнеторговым договорам" in quoted or "текст не выверен" in quoted

    def test_upload_is_deleted_after_check(
        self, compliant_docx: Path, tmp_path, monkeypatch
    ):
        uploads = tmp_path / "uploads"
        _post_check(_client(tmp_path, monkeypatch), compliant_docx)

        leftovers = [path for path in uploads.rglob("*") if path.is_file()]
        assert leftovers == []

    def test_unsupported_format_rejected(self, tmp_path, monkeypatch):
        client = _client(tmp_path, monkeypatch)
        response = client.post(
            "/check",
            files={"file": ("contract.txt", b"text", "text/plain")},
        )

        assert response.status_code == 400

    def test_empty_file_rejected(self, tmp_path, monkeypatch):
        client = _client(tmp_path, monkeypatch)
        response = client.post(
            "/check",
            files={
                "file": (
                    "пустой.docx",
                    b"",
                    DOCX_TYPE,
                )
            },
        )

        assert response.status_code == 400

    def test_oversize_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UPLOAD_TMP_DIR", str(tmp_path / "uploads"))
        monkeypatch.setenv("MAX_UPLOAD_MB", "1")
        get_settings.cache_clear()
        try:
            client = TestClient(app)
            response = client.post(
                "/check",
                files={"file": ("huge.docx", b"x" * (1024 * 1024 + 1), DOCX_TYPE)},
            )
        finally:
            get_settings.cache_clear()

        assert response.status_code == 413


class TestSearchEndpoint:
    def test_finds_foreign_trade_exception(self):
        response = TestClient(app).get(
            "/search",
            params={"q": "внешнеторговый договор резидент нерезидент"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["hits"]
        assert any("ст. 1" in hit["ref"] for hit in payload["hits"])

    def test_empty_query_rejected(self):
        response = TestClient(app).get("/search", params={"q": ""})

        assert response.status_code == 422


class TestPdfEndpoint:
    def test_returns_pdf(
        self, violating_docx: Path, tmp_path, monkeypatch, cyrillic_font
    ):
        response = _post_check(
            _client(tmp_path, monkeypatch),
            violating_docx,
            url="/check/pdf",
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/pdf")
        assert response.content.startswith(b"%PDF")
        assert len(response.content) > 1000

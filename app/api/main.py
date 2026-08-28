from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.api.uploads import stored_upload, validate_upload
from app.core.config import get_settings
from app.norms.search import get_search
from app.parsing.document import EmptyDocumentError, UnsupportedFormatError
from app.report.pdf import MissingCyrillicFontError, render_pdf
from app.report.serialize import serialize_report
from app.rules.contract import ContractView
from app.rules.engine import Report, evaluate
from app.rules.guardrail import CircumventionAttempt

app = FastAPI(
    title="LexCryptoAI",
    description=(
        "Проверка внешнеторговых контрактов с расчётами в цифровой валюте "
        "на соответствие ФЗ № 282-ФЗ, 283-ФЗ и 115-ФЗ. "
        "Загруженный файл удаляется сразу после формирования заключения."
    ),
    version="0.2.0",
)


@app.get("/health")
async def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "env": settings.app_env, "version": app.version}


def _check_upload(content: bytes, filename: str | None, moment: date | None) -> tuple[Report, str]:
    settings = get_settings()
    suffix = validate_upload(filename, content, settings.max_upload_mb * 1024 * 1024)
    source_name = Path(filename or f"document{suffix}").name
    with stored_upload(content, suffix, root=settings.upload_tmp_dir) as path:
        try:
            contract = ContractView.from_file(path)
        except UnsupportedFormatError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except EmptyDocumentError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            report = evaluate(contract, moment=moment)
        except CircumventionAttempt as error:
            raise HTTPException(
                status_code=500,
                detail="заключение не сформировано",
            ) from error
    return report, source_name


@app.post("/check")
async def check_contract(
    file: UploadFile = File(..., description="контракт в формате PDF или DOCX"),
    on: date | None = Query(None, description="дата проверки, ГГГГ-ММ-ДД"),
    quote_norms: bool = Query(False, description="включить дословный текст нормы"),
) -> dict:
    content = await file.read()
    report, source_name = _check_upload(content, file.filename, on)
    return serialize_report(report, source_name=source_name, quote_norms=quote_norms)


@app.post("/check/pdf")
async def check_contract_pdf(
    file: UploadFile = File(..., description="контракт в формате PDF или DOCX"),
    on: date | None = Query(None, description="дата проверки, ГГГГ-ММ-ДД"),
    quote_norms: bool = Query(False, description="включить дословный текст нормы"),
) -> Response:
    content = await file.read()
    report, source_name = _check_upload(content, file.filename, on)
    try:
        pdf = render_pdf(report, source_name=source_name, quote_norms=quote_norms)
    except MissingCyrillicFontError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="zaklyuchenie.pdf"'},
    )


@app.get("/search")
def search_norms(
    q: str = Query(..., min_length=1, description="формулировка"),
    limit: int = Query(5, ge=1, le=20),
    act: str | None = Query(None, description="ограничить акт, например 282-ФЗ"),
) -> dict:
    hits = get_search().search(q, limit=limit, act=act)
    return {
        "query": q,
        "hits": [
            {
                "ref": hit.norm.reference,
                "score": round(hit.score, 4),
                "text": hit.norm.text,
            }
            for hit in hits
        ],
    }

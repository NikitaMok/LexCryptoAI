"""PDF-заключение по результатам проверки.

Тексты те же, что в JSON и в консоли. Статические фразы проходят ту же
проверку, что и заключение: часть 2 статьи 30 № 282-ФЗ.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path

from reportlab.lib.colors import HexColor, black
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from app.norms.index import get_norms
from app.report.serialize import STATUS_LABEL, quote_norms_for
from app.rules.engine import ContractStatus, Finding, FindingStatus, Report
from app.rules.guardrail import assert_clean

FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("/Library/Fonts/Arial.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
)

FONT_NAME = "ReportCyrillic"

_STATUS_COLOR = {
    ContractStatus.GREEN: HexColor("#1B5E20"),
    ContractStatus.YELLOW: HexColor("#E65100"),
    ContractStatus.RED: HexColor("#B71C1C"),
}

_MONTHS = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}

TITLE = "Предварительная проверка внешнеторгового контракта"
SUBTITLE = (
    "на соответствие требованиям Федерального закона от 04.08.2026 № 282-ФЗ "
    "и связанных актов"
)
DISCLAIMER = (
    "Это предварительный аналитический отчёт. Он не является юридической "
    "консультацией и не заменяет проверку договора юристом. "
    "Нельзя предъявлять его банку, налоговому органу или контрагенту "
    "как подтверждение соответствия. Перед использованием результаты "
    "нужно перепроверить вручную. Проверка не является цифровым анализом "
    "в смысле статьи 35 Федерального закона от 04.08.2026 № 282-ФЗ."
)
FOOTER = (
    "Предварительный отчёт. Перепроверить вручную. Не для банка. "
    "Не юридическая консультация. Не цифровой анализ по ст. 35 № 282-ФЗ."
)
SECTION_BLOCKING = "Нарушены обязательные требования"
SECTION_ADVISORY = "Замечания"
SECTION_DEFERRED = "Нормы, вступающие в силу позднее"
SECTION_MANUAL = "Требует оценки юриста"
SECTION_ADDRESSES = "Адреса по открытым данным"


class MissingCyrillicFontError(RuntimeError):
    pass


def resolve_font() -> Path:
    for candidate in FONT_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise MissingCyrillicFontError(
        "не найден TTF-шрифт с кириллицей; установите DejaVu Sans или Arial"
    )


def _ensure_font() -> str:
    if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(resolve_font())))
    return FONT_NAME


def _xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def _format_date(value: date) -> str:
    return f"{value.day} {_MONTHS[value.month]} {value.year} г."


def _styles(font: str) -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle(
            "title",
            fontName=font,
            fontSize=14,
            leading=18,
            alignment=TA_CENTER,
            spaceAfter=4,
            textColor=black,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            fontName=font,
            fontSize=9,
            leading=12,
            alignment=TA_CENTER,
            spaceAfter=12,
            textColor=HexColor("#333333"),
        ),
        "status": ParagraphStyle(
            "status",
            fontName=font,
            fontSize=12,
            leading=16,
            alignment=TA_CENTER,
            spaceAfter=10,
        ),
        "meta": ParagraphStyle(
            "meta",
            fontName=font,
            fontSize=9,
            leading=12,
            alignment=TA_LEFT,
            spaceAfter=2,
        ),
        "heading": ParagraphStyle(
            "heading",
            fontName=font,
            fontSize=11,
            leading=14,
            spaceBefore=12,
            spaceAfter=6,
            textColor=black,
        ),
        "body": ParagraphStyle(
            "body",
            fontName=font,
            fontSize=9,
            leading=12,
            alignment=TA_JUSTIFY,
            spaceAfter=3,
        ),
        "indent": ParagraphStyle(
            "indent",
            fontName=font,
            fontSize=9,
            leading=12,
            leftIndent=10,
            spaceAfter=2,
        ),
        "quote": ParagraphStyle(
            "quote",
            fontName=font,
            fontSize=8,
            leading=11,
            leftIndent=14,
            alignment=TA_JUSTIFY,
            textColor=HexColor("#222222"),
            spaceAfter=4,
        ),
        "disclaimer": ParagraphStyle(
            "disclaimer",
            fontName=font,
            fontSize=8,
            leading=11,
            alignment=TA_JUSTIFY,
            spaceBefore=16,
            textColor=HexColor("#333333"),
        ),
    }


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont(FONT_NAME, 7)
    canvas.setFillColor(HexColor("#444444"))
    canvas.drawString(18 * mm, 12 * mm, FOOTER)
    canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, str(doc.page))
    canvas.restoreState()


def _finding_blocks(
    finding: Finding,
    styles: dict[str, ParagraphStyle],
    quoted: list[dict[str, str | None]] | None,
) -> list:
    blocks = [
        Paragraph(_xml(f"[{finding.code}] {finding.title}"), styles["body"]),
    ]
    if finding.evidence:
        blocks.append(Paragraph(_xml(finding.evidence), styles["indent"]))
    if finding.clauses:
        blocks.append(
            Paragraph(
                _xml("пункты договора: " + ", ".join(finding.clauses)),
                styles["indent"],
            )
        )
    if finding.norm_refs:
        refs = "; ".join(str(ref) for ref in finding.norm_refs)
        blocks.append(Paragraph(_xml(f"норма: {refs}"), styles["indent"]))
    if quoted:
        for item in quoted:
            if item["text"]:
                blocks.append(
                    Paragraph(_xml(f"{item['ref']}: {item['text']}"), styles["quote"])
                )
            elif item["note"]:
                blocks.append(
                    Paragraph(_xml(f"{item['ref']}: {item['note']}"), styles["quote"])
                )
    if finding.sanction:
        blocks.append(Paragraph(_xml(f"последствие: {finding.sanction}"), styles["indent"]))
    if finding.recommendation:
        blocks.append(Paragraph("как исправить:", styles["indent"]))
        blocks.append(Paragraph(_xml(finding.recommendation), styles["indent"]))
    blocks.append(Spacer(1, 6))
    return blocks


def render_pdf(
    report: Report,
    *,
    source_name: str,
    quote_norms: bool = False,
    address_scores: list | None = None,
) -> bytes:
    for fragment in (
        TITLE,
        SUBTITLE,
        DISCLAIMER,
        FOOTER,
        SECTION_BLOCKING,
        SECTION_ADVISORY,
        SECTION_ADDRESSES,
    ):
        assert_clean(fragment)

    font = _ensure_font()
    styles = _styles(font)
    index = get_norms() if quote_norms else None
    color = _STATUS_COLOR[report.status]
    styles["status"].textColor = color

    passed = sum(1 for finding in report.findings if finding.status is FindingStatus.PASSED)
    skipped = sum(
        1 for finding in report.findings if finding.status is FindingStatus.NOT_APPLICABLE
    )
    deferred = [finding for finding in report.findings if finding.status is FindingStatus.DEFERRED]
    manual = report.needs_manual_review()

    story: list = [
        Paragraph(_xml(TITLE), styles["title"]),
        Paragraph(_xml(SUBTITLE), styles["subtitle"]),
        Paragraph(_xml(f"Статус: {STATUS_LABEL[report.status]}"), styles["status"]),
        Paragraph(_xml(f"Документ: {Path(source_name).name}"), styles["meta"]),
        Paragraph(
            _xml(f"Проверено на дату: {_format_date(report.checked_on)}"),
            styles["meta"],
        ),
        Paragraph(
            _xml(
                f"Итого правил: {len(report.findings)}. Выполнено: {passed}. "
                f"Нарушено: {len(report.violations())}. Не применимо: {skipped}. "
                f"На ручной оценке: {len(manual)}."
            ),
            styles["meta"],
        ),
    ]

    blocking = report.blocking_violations()
    if blocking:
        story.append(Paragraph(_xml(SECTION_BLOCKING), styles["heading"]))
        for finding in blocking:
            quoted = quote_norms_for(finding, index) if index else None
            story.extend(_finding_blocks(finding, styles, quoted))

    advisory = report.advisory_violations()
    if advisory:
        story.append(Paragraph(_xml(SECTION_ADVISORY), styles["heading"]))
        for finding in advisory:
            story.extend(_finding_blocks(finding, styles, None))

    if deferred:
        story.append(Paragraph(_xml(SECTION_DEFERRED), styles["heading"]))
        for finding in deferred:
            story.extend(_finding_blocks(finding, styles, None))

    if manual:
        story.append(Paragraph(_xml(SECTION_MANUAL), styles["heading"]))
        for finding in manual:
            story.append(Paragraph(_xml(f"[{finding.code}] {finding.title}"), styles["body"]))

    if address_scores:
        story.append(Paragraph(_xml(SECTION_ADDRESSES), styles["heading"]))
        for item in address_scores:
            payload = item.to_dict() if hasattr(item, "to_dict") else item
            line = (
                f"{payload.get('address')} ({payload.get('network')}): "
                f"{payload.get('band')}"
            )
            if payload.get("score") is not None:
                line += f", оценка {payload['score']}"
            story.append(Paragraph(_xml(line), styles["body"]))
            for factor in payload.get("factors") or []:
                story.append(Paragraph(_xml(factor), styles["indent"]))
            if payload.get("error"):
                story.append(Paragraph(_xml(str(payload["error"])), styles["indent"]))
            if payload.get("disclaimer"):
                story.append(Paragraph(_xml(str(payload["disclaimer"])), styles["quote"]))

    story.append(Paragraph(_xml(DISCLAIMER), styles["disclaimer"]))

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
        title=TITLE,
        author="LexCryptoAI",
    )
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def write_pdf(
    report: Report,
    path: Path,
    *,
    source_name: str,
    quote_norms: bool = False,
    address_scores: list | None = None,
) -> None:
    path.write_bytes(
        render_pdf(
            report,
            source_name=source_name,
            quote_norms=quote_norms,
            address_scores=address_scores,
        )
    )

"""Render delivery Markdown as an evidence-preserving PDF."""

import base64
import io
import re
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    LongTable,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)
from reportlab.lib.utils import ImageReader

from api.adapters import branding as delivery_branding


_REPLACEMENTS = {
    "\u2192": "->",
    "\u2190": "<-",
    "\u2264": "<=",
    "\u2265": ">=",
    "\u2014": "-",
    "\u2013": "-",
    "\u00b7": " - ",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u00d7": "x",
    "\u00a0": " ",
}
_INLINE_TAG = re.compile(r"<[^>]+>")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def _safe_text(value):
    text = str(value or "")
    for source, replacement in _REPLACEMENTS.items():
        text = text.replace(source, replacement)
    return _INLINE_TAG.sub("", text)


def _inline(value, code_font="Courier"):
    text = escape(_safe_text(value))
    text = _LINK.sub(lambda match: f'<link href="{match.group(2)}">{match.group(1)}</link>', text)
    text = re.sub(r"`([^`]+)`", rf'<font name="{code_font}">\1</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    return text


def _cjk_font(text):
    """Return a built-in CID font for the document's dominant CJK script."""
    value = str(text or "")
    if re.search(r"[\uac00-\ud7af]", value):
        return "HYSMyeongJo-Medium"
    if re.search(r"[\u3040-\u30ff]", value):
        return "HeiseiMin-W3"
    if re.search(r"[\u3400-\u9fff]", value):
        return "STSong-Light"
    return None


def _register_cjk_font(name):
    if name and name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(name))


def _styles(cjk_font=None):
    base = getSampleStyleSheet()
    font = cjk_font or "Helvetica"
    bold = "Helvetica-Bold" if not cjk_font else cjk_font
    code_font = cjk_font or "Courier"
    return {
        "title": ParagraphStyle("PdfTitle", parent=base["Title"], fontName=bold, fontSize=18, leading=23, alignment=TA_LEFT, spaceAfter=8, textColor=colors.HexColor("#111827")),
        "meta": ParagraphStyle("PdfMeta", parent=base["BodyText"], fontName=font, fontSize=8, leading=12, textColor=colors.HexColor("#6b7280"), spaceAfter=18),
        "h2": ParagraphStyle("PdfH2", parent=base["Heading2"], fontName=bold, fontSize=14, leading=18, spaceBefore=16, spaceAfter=7, textColor=colors.HexColor("#111827")),
        "h3": ParagraphStyle("PdfH3", parent=base["Heading3"], fontName=bold, fontSize=11, leading=15, spaceBefore=12, spaceAfter=5, textColor=colors.HexColor("#1f2937")),
        "h4": ParagraphStyle("PdfH4", parent=base["Heading4"], fontName=bold, fontSize=9.5, leading=13, spaceBefore=9, spaceAfter=4, textColor=colors.HexColor("#374151")),
        "body": ParagraphStyle("PdfBody", parent=base["BodyText"], fontName=font, fontSize=9.5, leading=14, spaceAfter=7, textColor=colors.HexColor("#1f2937")),
        "quote": ParagraphStyle("PdfQuote", parent=base["BodyText"], fontName=font, fontSize=9, leading=13.5, leftIndent=10, textColor=colors.HexColor("#4b5563"), spaceAfter=7),
        "bullet": ParagraphStyle("PdfBullet", parent=base["BodyText"], fontName=font, fontSize=9.5, leading=13.5, textColor=colors.HexColor("#1f2937")),
        "code": ParagraphStyle("PdfCode", parent=base["Code"], fontName=code_font, fontSize=7.5, leading=10.5, textColor=colors.HexColor("#111827")),
        "cell": ParagraphStyle("PdfCell", parent=base["BodyText"], fontName=font, fontSize=7.5, leading=10, textColor=colors.HexColor("#1f2937")),
        "_code_font": code_font,
        "_header_font": bold,
    }


def _table(rows, styles, available_width):
    if not rows:
        return None
    columns = max(len(row) for row in rows)
    normalized = [row + [""] * (columns - len(row)) for row in rows]
    data = [[Paragraph(_inline(cell, styles["_code_font"]), styles["cell"]) for cell in row] for row in normalized]
    table = LongTable(data, colWidths=[available_width / columns] * columns, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("FONTNAME", (0, 0), (-1, 0), styles["_header_font"]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _markdown_story(markdown, styles, available_width):
    lines = _safe_text(markdown).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    inline = lambda value: _inline(value, styles["_code_font"])
    story = []
    paragraph = []
    in_code = False
    code_lines = []
    index = 0

    def flush_paragraph():
        if paragraph:
            story.append(Paragraph(inline(" ".join(paragraph)), styles["body"]))
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_paragraph()
            if in_code:
                story.append(Preformatted("\n".join(code_lines), styles["code"]))
                code_lines.clear()
                in_code = False
            else:
                in_code = True
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue
        if not stripped:
            flush_paragraph()
            index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            style = "title" if level == 1 else "h2" if level == 2 else "h3" if level == 3 else "h4"
            story.append(Paragraph(inline(heading.group(2)), styles[style]))
            index += 1
            continue
        if re.fullmatch(r"[-*_]{3,}", stripped):
            flush_paragraph()
            story.append(Spacer(1, 8))
            index += 1
            continue
        if stripped.startswith(">"):
            flush_paragraph()
            story.append(Paragraph(inline(stripped.lstrip("> ")), styles["quote"]))
            index += 1
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_paragraph()
            rows = []
            while index < len(lines):
                candidate = lines[index].strip()
                if not (candidate.startswith("|") and candidate.endswith("|")):
                    break
                cells = [cell.strip() for cell in candidate.strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells if cell):
                    rows.append(cells)
                index += 1
            table = _table(rows, styles, available_width)
            if table:
                story.extend([table, Spacer(1, 8)])
            continue
        bullet = re.match(r"^[-*+]\s+(.+)$", stripped)
        ordered = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if bullet or ordered:
            flush_paragraph()
            items = []
            ordered_type = bool(ordered)
            while index < len(lines):
                candidate = lines[index].strip()
                match = re.match(r"^[-*+]\s+(.+)$" if not ordered_type else r"^\d+[.)]\s+(.+)$", candidate)
                if not match:
                    break
                items.append(ListItem(Paragraph(inline(match.group(1)), styles["bullet"])))
                index += 1
            story.append(ListFlowable(items, bulletType="1" if ordered_type else "bullet", leftIndent=14, bulletFontName="Helvetica", bulletFontSize=8))
            story.append(Spacer(1, 6))
            continue
        paragraph.append(stripped)
        index += 1

    flush_paragraph()
    if code_lines:
        story.append(Preformatted("\n".join(code_lines), styles["code"]))
    return story


def _logo_image(branding):
    value = str(branding.get("logo_data_url") or "")
    if not value:
        return None
    match = re.fullmatch(r"data:image/(?:png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", value)
    if not match:
        return None
    try:
        raw = base64.b64decode(match.group(1), validate=True)
        reader = ImageReader(io.BytesIO(raw))
        width, height = reader.getSize()
        if not width or not height:
            return None
        max_width, max_height = 108, 24
        scale = min(max_width / width, max_height / height)
        return Image(io.BytesIO(raw), width=width * scale, height=height * scale)
    except Exception:
        return None


def _draw_page(canvas, doc, *, title, metadata, branding, footer_text, text_font="Helvetica"):
    width, height = A4
    accent = colors.HexColor(branding.get("accent_color") or "#1F4E79")
    company = branding.get("company_name") if branding.get("enabled") else ""
    canvas.saveState()
    canvas.setStrokeColor(accent)
    canvas.setLineWidth(0.8)
    canvas.line(42, height - 35, width - 42, height - 35)
    if company:
        canvas.setFont(text_font, 7.5)
        canvas.setFillColor(colors.HexColor("#374151"))
        canvas.drawString(42, height - 28, _safe_text(company))
    separator = " | " if text_font != "Helvetica" else " · "
    meta = separator.join(value for value in metadata.values() if value)
    if meta:
        canvas.setFont(text_font, 6.8)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawRightString(width - 42, height - 28, _safe_text(meta)[:130])
    canvas.setStrokeColor(colors.HexColor("#e5e7eb"))
    canvas.line(42, 34, width - 42, 34)
    canvas.setFont(text_font, 6.8)
    canvas.setFillColor(colors.HexColor("#6b7280"))
    left = _safe_text(footer_text or company or "CiteAura")
    canvas.drawString(42, 22, left[:90])
    canvas.drawRightString(width - 42, 22, f"{_safe_text(title)} / {doc.page}")
    canvas.restoreState()


def render_markdown_pdf(markdown, *, title=None, metadata=None, branding=None, footer_text=""):
    """Return a PDF byte string for a delivery Markdown document."""
    metadata = {key: _safe_text(value) for key, value in (metadata or {}).items() if value}
    branding = branding or delivery_branding.default_branding()
    first_heading = next((line[2:].strip() for line in str(markdown).splitlines() if line.startswith("# ")), "")
    title = _safe_text(title or first_heading or "CiteAura delivery")
    metadata_text = " ".join(f"{key} {value}" for key, value in metadata.items() if value)
    cjk_font = _cjk_font(" ".join([str(markdown), title, metadata_text, str(footer_text or "")]))
    meta_line = (" | " if cjk_font else " · ").join(f"{key}: {value}" for key, value in metadata.items() if value)
    _register_cjk_font(cjk_font)
    styles = _styles(cjk_font)
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=42,
        rightMargin=42,
        topMargin=50,
        bottomMargin=44,
        title=title,
        author=_safe_text(branding.get("company_name") or "CiteAura"),
        subject="CiteAura delivery evidence",
    )
    body = str(markdown)
    if first_heading:
        body = body.replace(f"# {first_heading}", "", 1)
    story = [Paragraph(_inline(title, styles["_code_font"]), styles["title"])]
    if meta_line:
        story.append(Paragraph(_inline(meta_line, styles["_code_font"]), styles["meta"]))
    story.extend(_markdown_story(body, styles, document.width))
    logo = _logo_image(branding)
    if logo:
        story.insert(0, KeepTogether([logo, Spacer(1, 8)]))
    document.build(
        story,
        onFirstPage=lambda canvas, doc: _draw_page(canvas, doc, title=title, metadata=metadata, branding=branding, footer_text=footer_text, text_font=cjk_font or "Helvetica"),
        onLaterPages=lambda canvas, doc: _draw_page(canvas, doc, title=title, metadata=metadata, branding=branding, footer_text=footer_text, text_font=cjk_font or "Helvetica"),
    )
    return output.getvalue()


def pdf_filename(document_name, delivery_date, project_slug=""):
    stem = str(document_name or "report").removesuffix(".md").removesuffix(".html")
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", str(project_slug or "")).strip("-")
    parts = ["citeaura", slug, stem, str(delivery_date or date.today().isoformat())]
    return "-".join(part for part in parts if part) + ".pdf"


__all__ = ["render_markdown_pdf", "pdf_filename"]

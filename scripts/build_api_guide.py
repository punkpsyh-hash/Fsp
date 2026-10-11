"""Русское руководство API: standalone PDF, без сети и дополнительных пакетов.

Запускать через Docker tools. Исходник, шрифт и скрипт могут быть read-only;
запись нужна только каталогу результата PDF и JSON-протоколу.
"""
from __future__ import annotations

import argparse
import hashlib
from html import escape
import json
from pathlib import Path
import re

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, PageBreak
from gost_layout import GostContext, GostDocTemplate, figure_flowables, FONT_BOLD, FONT_REGULAR, FONT_MONO

ROOT = Path(__file__).resolve().parents[1]
PAGE_W, PAGE_H = A4
LEFT, RIGHT, TOP, BOTTOM = 30 * mm, 15 * mm, 20 * mm, 20 * mm
WIDTH = PAGE_W - LEFT - RIGHT
INK = BLUE = MUTED = colors.black
CHECKS: list[dict] = []
TOKEN = re.compile(r"(`[^`]+`|\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*|\*[^*]+\*)")


def inline(text: str) -> str:
    """Экранируем исходный HTML; допускаем только собственную разметку PDF."""
    result = []
    for token in TOKEN.split(text):
        if token.startswith("`") and token.endswith("`"):
            result.append(escape(token[1:-1]))
        elif token.startswith("**") and token.endswith("**"):
            result.append("<b>" + escape(token[2:-2]) + "</b>")
        elif token.startswith("*") and token.endswith("*"):
            result.append("<i>" + escape(token[1:-1]) + "</i>")
        elif token.startswith("["):
            match = re.fullmatch(r"\[([^\]]+)\]\(([^)]+)\)", token)
            if match:
                label, target = match.groups()
                result.append(escape(label) + " (" + escape(target) + ")")
            else:
                result.append(escape(token))
        else:
            result.append(escape(token))
    return "".join(result)


class CheckedParagraph(Paragraph):
    """Проверяем реальные координаты каждого отрисованного текстового блока."""

    def drawOn(self, canvas, x, y, _sW=0):
        adjusted_x = self._hAlignAdjust(x, _sW)
        left, bottom = canvas.absolutePosition(adjusted_x, y)
        right, top = canvas.absolutePosition(adjusted_x + self.width, y + self.height)
        tolerance = 0.75  # float rounding; документ явно сообщает предел проверки
        valid = (
            LEFT - tolerance <= left <= right <= PAGE_W - RIGHT + tolerance
            and BOTTOM - tolerance <= bottom <= top <= PAGE_H - TOP + tolerance
        )
        CHECKS.append({"page": canvas.getPageNumber(), "bounds": [round(v, 3) for v in (left, bottom, right, top)], "valid": valid})
        if not valid:
            raise ValueError(f"Текстовый блок за пределами рабочей области: {CHECKS[-1]}")
        return super().drawOn(canvas, x, y, _sW)


def styles():
    common = dict(fontName="FspApiRU", textColor=INK, splitLongWords=True,
                  allowWidows=0, allowOrphans=0)
    return {
        "body": ParagraphStyle("body", fontSize=14, leading=21, firstLineIndent=12.5*mm, alignment=TA_JUSTIFY, **common),
        "h1": ParagraphStyle("h1", fontSize=16, leading=24, spaceAfter=21, keepWithNext=True, **common),
        "h2": ParagraphStyle("h2", fontSize=14, leading=21, spaceBefore=21, spaceAfter=10.5, keepWithNext=True, **common),
        "h3": ParagraphStyle("h3", fontSize=14, leading=21, spaceBefore=10.5, spaceAfter=0, keepWithNext=True, **common),
        "h4": ParagraphStyle("h4", fontSize=14, leading=21, spaceBefore=10.5, spaceAfter=0, keepWithNext=True, **common),
        "list": ParagraphStyle("list", fontSize=14, leading=21, leftIndent=17, firstLineIndent=-13, **common),
        "code": ParagraphStyle("code", fontSize=12, leading=15, leftIndent=9, rightIndent=9, **{**common, 'fontName': FONT_MONO}),
        "field": ParagraphStyle("field", fontSize=14, leading=21, leftIndent=10, **common),
        "note": ParagraphStyle("note", fontSize=12, leading=15, spaceAfter=5, **common),
    }


def cells(line: str) -> list[str]:
    return [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def is_separator(line: str) -> bool:
    parts = cells(line)
    return bool(parts) and all(re.fullmatch(r":?-{3,}:?", part) for part in parts)


def wrap_code(line: str) -> list[str]:
    """Физическая ширина шрифта, а не предположение о числе символов."""
    line = line.expandtabs(4)
    if not line:
        return [""]
    chunks, current = [], ""
    for char in line:
        if current and pdfmetrics.stringWidth(current + char, FONT_MONO, 12) > WIDTH - 32:
            chunks.append(current)
            current = ""
        current += char
    chunks.append(current)
    return chunks


def markdown_story(source: str, st: dict, context=None):
    context = context or GostContext()
    lines = source.splitlines()
    story, stats = [], {"headings": 0, "code_blocks": 0, "tables": 0, "operation_rows": 0}
    index = 0
    first_h1 = True

    def paragraph(text, kind="body"):
        return CheckedParagraph(inline(context.resolve_references(text)), st[kind])

    while index < len(lines):
        line = lines[index].strip()
        if not line or re.fullmatch(r"[-*_]{3,}", line):
            index += 1
            continue
        figure = re.fullmatch(r"<!--\s*figure:([\w.-]+)\s*-->", line)
        if figure:
            story.extend(figure_flowables(figure.group(1), context))
            index += 1
            continue
        if line.startswith('<!--'):
            index += 1
            continue
        if line.startswith("```"):
            language = line[3:].strip()
            stats["code_blocks"] += 1
            code_block = [paragraph("Пример" + (" · " + language if language else ""), "note")]
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                for chunk in wrap_code(lines[index]):
                    markup = escape(chunk).replace(" ", "&#160;") or "&#160;"
                    code_block.append(CheckedParagraph(markup, st["code"]))
                index += 1
            if index == len(lines):
                raise ValueError("Незакрытый блок кода в Markdown")
            story.extend(code_block)
            story.append(Spacer(1, 9))
            index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            stats["headings"] += 1
            if len(heading[1]) == 1:
                if first_h1:
                    first_h1 = False
                    index += 1
                    continue
                story.append(PageBreak())
            story.append(paragraph('**' + heading[2] + '**', "h" + str(min(len(heading[1]), 4))))
            index += 1
            continue
        if index + 1 < len(lines) and "|" in line and is_separator(lines[index + 1]):
            headers = cells(line)
            operation = "Метод" in headers and "Путь" in headers
            stats["tables"] += 1
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                row = cells(lines[index])
                if len(row) != len(headers):
                    raise ValueError(f"Строка таблицы {index + 1}: число колонок не совпадает")
                block = []
                if operation:
                    stats["operation_rows"] += 1
                    block.append(paragraph(row[headers.index("Метод")] + " " + row[headers.index("Путь")], "h3"))
                    excluded = {"Метод", "Путь"}
                else:
                    block.append(paragraph(headers[0] + ": " + row[0], "h3"))
                    excluded = {headers[0]}
                for header, value in zip(headers, row):
                    if header not in excluded:
                        block.append(paragraph("**" + header + ":** " + value, "field"))
                story.append(KeepTogether(block))
                index += 1
            story.append(Spacer(1, 5))
            continue
        list_item = re.match(r"^(-|\*|\d+[.)])\s+(.+)$", line)
        if list_item:
            marker = "•" if list_item[1] in ("-", "*") else list_item[1]
            text = list_item[2]
            index += 1
            while index < len(lines) and lines[index].startswith(("  ", "\t")) and lines[index].strip() and not lines[index].strip().startswith("```"):
                text += " " + lines[index].strip()
                index += 1
            story.append(paragraph(marker + " " + text, "list"))
            continue
        text = line[2:] if line.startswith("> ") else line
        index += 1
        while index < len(lines):
            following = lines[index].strip()
            if not following or re.match(r"^(#{1,6}\s|```|[-*]\s|\d+[.)]\s|\|)", following):
                break
            text += " " + following
            index += 1
        story.append(paragraph(text))
    return story, stats


def decoration(canvas, document):
    canvas.saveState()
    canvas.setFont("FspApiRU", 12)
    canvas.setFillColor(MUTED)
    if document.page > 1:
        canvas.drawCentredString(PAGE_W / 2, 10 * mm, str(document.page))
    canvas.restoreState()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "docs/18-api-guide.md")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/delivery/gost/api-guide.pdf")
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "docs/release/current-documents/api-pdf.json",
    )
    parser.add_argument("--font", type=Path, default=ROOT / "resources/fonts/Tinos-Regular.ttf")
    parser.add_argument("--check-reproducibility", action="store_true", help="Дважды построить PDF и сравнить реальные SHA-256")
    args = parser.parse_args()
    pdfmetrics.registerFont(TTFont("FspApiRU", str(args.font)))
    pdfmetrics.registerFontFamily("FspApiRU", normal="FspApiRU", bold=FONT_BOLD, italic=FONT_REGULAR, boldItalic=FONT_BOLD)
    source_bytes = args.source.read_bytes()
    def with_cover():
        st = styles()
        body, stats = markdown_story(source_bytes.decode('utf-8'), st)
        cover = [Spacer(1, 55), CheckedParagraph('<b>ФСП Карьерный профиль</b>', st['h1']),
                 CheckedParagraph('<b>Практическое руководство по локальному API</b>', st['h1']),
                 CheckedParagraph('11 октября 2026 года', st['note']),
                 CheckedParagraph('88 путей / 101 операция. Описывается API проекта, включая отдельный режим показа жюри. Все демонстрационные данные синтетические.', st['body']), PageBreak()]
        return cover + body, stats
    story, statistics = with_cover()
    if not story:
        raise ValueError("Руководство не содержит текста")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    first_hash = None
    for build_number in range(2 if args.check_reproducibility else 1):
        if build_number:
            story, statistics = with_cover()
        CHECKS.clear()
        document = GostDocTemplate(str(args.output), pagesize=A4, leftMargin=LEFT, rightMargin=RIGHT, topMargin=TOP, bottomMargin=BOTTOM, title="ФСП · Практическое руководство по локальному API", author="Проект Fsp", pageCompression=True, invariant=True)
        document.build(story, onFirstPage=decoration, onLaterPages=decoration, canvasmaker=Canvas)
        actual_hash = hashlib.sha256(args.output.read_bytes()).hexdigest()
        if first_hash is not None:
            assert actual_hash == first_hash, "Повторный PDF отличается побайтно"
        first_hash = actual_hash
    pdf_bytes = args.output.read_bytes()
    reader = PdfReader(args.output)
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Практическое руководство" in extracted, "Русский заголовок не извлекается из PDF"
    assert "```" not in extracted, "В PDF остались сырые ограждения Markdown"
    assert CHECKS and all(check["valid"] for check in CHECKS)
    # Перенос пути между строками допустим; потеря символов операции — нет.
    operation_markers = []
    for line in source_bytes.decode("utf-8").splitlines():
        if re.match(r"^\|\s*(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s*\|", line):
            row = cells(line)
            operation_markers.append(row[0].strip("`") + row[1].strip("`"))
    compact_pdf = re.sub(r"\s+", "", extracted)
    missing_operations = [marker for marker in operation_markers if re.sub(r"\s+", "", marker) not in compact_pdf]
    assert not missing_operations, f"Операции не извлекаются из PDF: {missing_operations}"
    assert len(operation_markers) == statistics["operation_rows"]
    report = {
        "source": args.source.name,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "pdf": args.output.name,
        "pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "pdf_bytes": len(pdf_bytes),
        "pages": len(reader.pages),
        "invariant_pdf": True,
        "source_structure": statistics,
        "checks": {
            "cyrillic_text_extractable": True,
            "byte_reproducibility_verified": args.check_reproducibility,
            "raw_code_fences_absent": True,
            "operations_extractable": len(operation_markers),
            "missing_operations": [],
            "drawn_text_blocks": len(CHECKS),
            "flowable_bounds_valid": True,
            "overflow_blocks": 0,
            "page_size_pt": [round(PAGE_W, 3), round(PAGE_H, 3)],
            "body_margins_pt": {"left": LEFT, "right": RIGHT, "top": TOP, "bottom": BOTTOM},
            "bounds_tolerance_pt": 0.75,
            "scope": "Проверены реальные прямоугольники отрисованных Paragraph, включая блоки, разбитые между страницами. Это проверка геометрии ReportLab, не независимая растровая проверка каждого глифа или визуальная приёмка.",
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pages": report["pages"], "operation_rows": statistics["operation_rows"], "flowable_bounds_valid": True, "pdf_sha256": report["pdf_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

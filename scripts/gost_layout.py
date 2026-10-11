"""Общие правила вёрстки PDF по ГОСТ 7.32-2017 для документации проекта.

Модуль не содержит предметного текста документов. Он задаёт воспроизводимую
типографику, поля, нумерацию, таблицы, рисунки и небольшой Markdown-парсер.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
import json
import os
from pathlib import Path
import re
from typing import Iterable

from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    XPreformatted,
)
from reportlab.platypus.doctemplate import _doNothing


ROOT = Path(__file__).resolve().parents[1]
PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT_MARGIN = 30 * mm
RIGHT_MARGIN = 15 * mm
TOP_MARGIN = 20 * mm
BOTTOM_MARGIN = 20 * mm
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN
FIRST_LINE_INDENT = 12.5 * mm
BLACK = colors.black
LIGHT_GRAY = colors.HexColor("#F2F2F2")

FONT_REGULAR = "GostSerif"
FONT_BOLD = "GostSerifBold"
FONT_ITALIC = "GostSerifItalic"
FONT_BOLD_ITALIC = "GostSerifBoldItalic"
FONT_MONO = "GostMono"


def _font_path(env_name: str, default_name: str) -> Path:
    configured = os.environ.get(env_name)
    return Path(configured) if configured else ROOT / "resources" / "fonts" / default_name


def register_fonts() -> None:
    """Регистрирует Times-совместимый Tinos или явно заданные TTF-файлы.

    Для лицензионной Times New Roman можно передать четыре переменные
    FSP_GOST_FONT_*. Без настройки используется включённый в проект Tinos.
    """
    serif = {
        FONT_REGULAR: _font_path("FSP_GOST_FONT_REGULAR", "Tinos-Regular.ttf"),
        FONT_BOLD: _font_path("FSP_GOST_FONT_BOLD", "Tinos-Bold.ttf"),
        FONT_ITALIC: _font_path("FSP_GOST_FONT_ITALIC", "Tinos-Italic.ttf"),
        FONT_BOLD_ITALIC: _font_path("FSP_GOST_FONT_BOLD_ITALIC", "Tinos-BoldItalic.ttf"),
    }
    missing = [str(path) for path in serif.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Не найдены шрифты ГОСТ: " + ", ".join(missing))
    for name, path in serif.items():
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(path)))
    pdfmetrics.registerFontFamily(
        FONT_REGULAR,
        normal=FONT_REGULAR,
        bold=FONT_BOLD,
        italic=FONT_ITALIC,
        boldItalic=FONT_BOLD_ITALIC,
    )

    # Отдельный TTF можно смонтировать через FSP_GOST_MONO_FONT. Стандартная
    # поставка использует свободный JetBrains Mono из ресурсов проекта.
    mono = Path(os.environ.get("FSP_GOST_MONO_FONT", ROOT / "resources" / "fonts" / "JetBrainsMono-Regular.ttf"))
    if not mono.is_file():
        raise FileNotFoundError(f"Не найден шрифт для блоков кода: {mono}")
    if FONT_MONO not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_MONO, str(mono)))


register_fonts()


STYLES = {
    "body": ParagraphStyle(
        "body",
        fontName=FONT_REGULAR,
        fontSize=14,
        leading=21,
        firstLineIndent=FIRST_LINE_INDENT,
        alignment=TA_JUSTIFY,
        textColor=BLACK,
        splitLongWords=True,
        allowWidows=0,
        allowOrphans=0,
    ),
    "h1": ParagraphStyle(
        "h1",
        fontName=FONT_BOLD,
        fontSize=14,
        leading=21,
        alignment=TA_CENTER,
        spaceBefore=21,
        spaceAfter=21,
        keepWithNext=True,
        textColor=BLACK,
    ),
    "h2": ParagraphStyle(
        "h2",
        fontName=FONT_BOLD,
        fontSize=14,
        leading=21,
        firstLineIndent=FIRST_LINE_INDENT,
        spaceBefore=21,
        spaceAfter=0,
        keepWithNext=True,
        textColor=BLACK,
    ),
    "h3": ParagraphStyle(
        "h3",
        fontName=FONT_BOLD,
        fontSize=14,
        leading=21,
        firstLineIndent=FIRST_LINE_INDENT,
        spaceBefore=10.5,
        spaceAfter=0,
        keepWithNext=True,
        textColor=BLACK,
    ),
    "title": ParagraphStyle(
        "title",
        fontName=FONT_BOLD,
        fontSize=16,
        leading=24,
        alignment=TA_CENTER,
        spaceAfter=21,
        keepWithNext=True,
        textColor=BLACK,
    ),
    "title_meta": ParagraphStyle(
        "title_meta",
        fontName=FONT_REGULAR,
        fontSize=14,
        leading=21,
        alignment=TA_CENTER,
        spaceAfter=21,
        textColor=BLACK,
    ),
    "bullet": ParagraphStyle(
        "bullet",
        fontName=FONT_REGULAR,
        fontSize=14,
        leading=21,
        bulletFontName=FONT_REGULAR,
        bulletFontSize=14,
        leftIndent=FIRST_LINE_INDENT,
        firstLineIndent=-7 * mm,
        bulletIndent=0,
        alignment=TA_JUSTIFY,
        textColor=BLACK,
        splitLongWords=True,
    ),
    "reference": ParagraphStyle(
        "reference",
        parent=None,
        fontName=FONT_REGULAR,
        fontSize=14,
        leading=21,
        firstLineIndent=FIRST_LINE_INDENT,
        alignment=TA_JUSTIFY,
        keepWithNext=True,
        textColor=BLACK,
    ),
    "code": ParagraphStyle(
        "code",
        fontName=FONT_MONO,
        fontSize=12,
        leading=15,
        alignment=TA_LEFT,
        textColor=BLACK,
        splitLongWords=True,
        wordWrap="CJK",
    ),
    "cell": ParagraphStyle(
        "cell",
        fontName=FONT_REGULAR,
        fontSize=12,
        leading=15,
        alignment=TA_LEFT,
        textColor=BLACK,
        splitLongWords=True,
        wordWrap="CJK",
    ),
    "cellh": ParagraphStyle(
        "cellh",
        fontName=FONT_BOLD,
        fontSize=12,
        leading=15,
        alignment=TA_LEFT,
        textColor=BLACK,
        splitLongWords=True,
        wordWrap="CJK",
    ),
    "small": ParagraphStyle(
        "small",
        fontName=FONT_REGULAR,
        fontSize=12,
        leading=15,
        firstLineIndent=FIRST_LINE_INDENT,
        alignment=TA_JUSTIFY,
        textColor=BLACK,
    ),
    "caption": ParagraphStyle(
        "caption",
        fontName=FONT_REGULAR,
        fontSize=12,
        leading=15,
        alignment=TA_CENTER,
        spaceBefore=6,
        spaceAfter=6,
        textColor=BLACK,
    ),
    "source": ParagraphStyle(
        "source",
        fontName=FONT_REGULAR,
        fontSize=12,
        leading=15,
        alignment=TA_LEFT,
        spaceAfter=6,
        textColor=BLACK,
    ),
    "table_title": ParagraphStyle(
        "table_title",
        fontName=FONT_REGULAR,
        fontSize=12,
        leading=15,
        alignment=TA_LEFT,
        spaceBefore=6,
        spaceAfter=6,
        keepWithNext=True,
        textColor=BLACK,
    ),
}


LINK = re.compile(r"\[([^]]+)\]\([^)]+\)")
IMAGE = re.compile(r"^!\[([^]]*)\]\(([^)]+)\)\s*$")
FIGURE_MARKER = re.compile(r"<!--\s*figure:([\w.-]+)\s*-->")
TABLE_MARKER = re.compile(r"<!--\s*table:(?:(?P<id>[\w.-]+)\s*\|\s*)?(?P<caption>.*?)\s*-->")
REFERENCE = re.compile(
    r"(?:\{\{(figure|table):([\w.-]+)\}\}|\[\[(figure|table):([\w.-]+)\]\])"
)
FIGURE_REFERENCE = re.compile(r"(?:\[\[figure:|\{\{figure:|\bрисунк\w*\b)", re.IGNORECASE)

SOURCE_END_TAIL_HEIGHT = 6 * STYLES["body"].leading
SOURCE_END_GROUP_HEIGHT = 12 * STYLES["body"].leading


def _plain(text: object) -> str:
    return LINK.sub(lambda match: match.group(1), str(text)).replace("`", "").replace("**", "")


@dataclass
class GostContext:
    """Сквозная нумерация и каталог иллюстраций одного PDF."""

    manifest_path: Path = ROOT / "docs" / "assets" / "screenshots" / "manifest.json"
    figure_count: int = 0
    table_count: int = 0
    figure_numbers: dict[str, int] = field(default_factory=dict)
    table_numbers: dict[str, int] = field(default_factory=dict)
    rendered_figures: set[str] = field(default_factory=set)
    _manifest: dict[str, dict] | None = None

    def figure_number(self, figure_id: str) -> int:
        if figure_id not in self.figure_numbers:
            self.figure_count += 1
            self.figure_numbers[figure_id] = self.figure_count
        return self.figure_numbers[figure_id]

    def table_number(self, table_id: str | None = None) -> int:
        if table_id and table_id in self.table_numbers:
            return self.table_numbers[table_id]
        self.table_count += 1
        if table_id:
            self.table_numbers[table_id] = self.table_count
        return self.table_count

    def resolve_references(self, text: str) -> str:
        def replace(match: re.Match) -> str:
            kind = match.group(1) or match.group(3)
            ref_id = match.group(2) or match.group(4)
            if kind == "figure":
                prefix = text[:match.start()].rstrip().lower()
                noun = 'рисунке' if re.search(r'\b(?:на|в)$', prefix) else 'рисунок'
                return f"{noun} {self.figure_number(ref_id)}"
            return f"таблица {self.table_number(ref_id)}"

        return REFERENCE.sub(replace, text)

    def manifest(self) -> dict[str, dict]:
        if self._manifest is not None:
            return self._manifest
        if not self.manifest_path.is_file():
            self._manifest = {}
            return self._manifest
        raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            values = raw.get("figures", raw.get("screenshots", raw))
        else:
            values = raw
        if isinstance(values, dict):
            entries = []
            for key, value in values.items():
                if isinstance(value, str):
                    value = {"path": value}
                if isinstance(value, dict):
                    entries.append({"id": key, **value})
        elif isinstance(values, list):
            entries = values
        else:
            raise ValueError(f"Неподдерживаемая структура manifest: {self.manifest_path}")
        self._manifest = {str(entry["id"]): entry for entry in entries if isinstance(entry, dict) and entry.get("id")}
        return self._manifest

    def figure(self, figure_id: str) -> dict:
        try:
            return self.manifest()[figure_id]
        except KeyError as error:
            raise KeyError(f"Иллюстрация {figure_id!r} отсутствует в {self.manifest_path}") from error


def para(text: object, kind: str = "body", context: GostContext | None = None) -> Paragraph:
    value = str(text)
    if context:
        value = context.resolve_references(value)
    return Paragraph(escape(_plain(value)), STYLES[kind])


def _scaled_widths(widths: Iterable[float] | None, columns: int) -> list[float]:
    values = list(widths) if widths else [1] * columns
    total = sum(values)
    if total <= 0:
        raise ValueError("Ширина таблицы должна быть положительной")
    return [CONTENT_WIDTH * value / total for value in values]


def make_table(rows: list[list[object]], widths: Iterable[float] | None = None) -> Table:
    if not rows or not rows[0]:
        raise ValueError("Нельзя построить пустую таблицу")
    columns = len(rows[0])
    if any(len(row) != columns for row in rows):
        raise ValueError("Во всех строках таблицы должно быть одинаковое число столбцов")
    data = [
        [Paragraph(escape(_plain(cell)), STYLES["cellh" if row_index == 0 else "cell"]) for cell in row]
        for row_index, row in enumerate(rows)
    ]
    table = Table(
        data,
        colWidths=_scaled_widths(widths, columns),
        repeatRows=1,
        splitByRow=1,
        splitInRow=1,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), LIGHT_GRAY),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.5, BLACK),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def table_flowables(
    rows: list[list[object]],
    widths: Iterable[float] | None = None,
    caption: str = "Сведения документа",
    context: GostContext | None = None,
    table_id: str | None = None,
) -> list:
    context = context or GostContext()
    number = context.table_number(table_id)
    return [
        para(f"Сведения приведены в таблице {number}.", "reference"),
        Paragraph(escape(f"Таблица {number} — {caption}"), STYLES["table_title"]),
        make_table(rows, widths),
    ]


def fit_drawing(drawing: Drawing) -> Drawing:
    """Уменьшает прежние схемы шириной 507 pt до рабочей области ГОСТ."""
    if drawing.width <= CONTENT_WIDTH:
        return drawing
    scale = CONTENT_WIDTH / drawing.width
    drawing.scale(scale, scale)
    drawing.width *= scale
    drawing.height *= scale
    return drawing


def drawing_flowables(drawing: Drawing, caption: str, figure_id: str, context: GostContext) -> list:
    number = context.figure_number(figure_id)
    if figure_id in context.rendered_figures:
        return [para(f"Иллюстрация ранее приведена на рисунке {number}.", "body")]
    context.rendered_figures.add(figure_id)
    return [
        KeepTogether(
            [
                para(f"Схема показана на рисунке {number}.", "reference"),
                fit_drawing(drawing),
                Paragraph(escape(f"Рисунок {number} — {caption}"), STYLES["caption"]),
            ]
        )
    ]


def _resolve_image_path(raw_path: str | Path, manifest_path: Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute() and path.is_file():
        return path
    for candidate in (ROOT / path, manifest_path.parent / path):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Не найден файл иллюстрации: {raw_path}")


def figure_flowables(
    figure_id: str,
    context: GostContext,
    *,
    path: str | Path | None = None,
    caption: str | None = None,
    source: str | None = None,
) -> list:
    entry = context.figure(figure_id) if path is None else {}
    image_path = _resolve_image_path(path or entry.get("path", ""), context.manifest_path)
    caption = str(caption or entry.get("caption") or "").strip()
    if not caption:
        raise ValueError(f"У иллюстрации {figure_id!r} отсутствует подпись")
    source = source or entry.get("source")
    number = context.figure_number(figure_id)
    if figure_id in context.rendered_figures:
        return [para(f"Иллюстрация ранее приведена на рисунке {number}.", "body")]
    context.rendered_figures.add(figure_id)
    image_width, image_height = ImageReader(str(image_path)).getSize()
    max_height = 0.58 * (PAGE_HEIGHT - TOP_MARGIN - BOTTOM_MARGIN)
    scale = min(CONTENT_WIDTH / image_width, max_height / image_height, 1)
    blocks = [
        Image(str(image_path), width=image_width * scale, height=image_height * scale),
        Paragraph(escape(f"Рисунок {number} — {caption}"), STYLES["caption"]),
    ]
    if source:
        blocks.append(Paragraph(escape(f"Источник: {source}"), STYLES["source"]))
    return [KeepTogether(blocks)]


def figures_appendix(
    story: list,
    ids: Iterable[str],
    context: GostContext | None = None,
    heading: str = "Приложение. Иллюстрации интерфейса",
) -> GostContext:
    """Добавляет в story иллюстрации из manifest с подписями и источниками."""
    context = context or GostContext()
    figure_ids = list(ids)
    if not figure_ids:
        return context
    story.extend([PageBreak(), para(heading, "h1", context)])
    for figure_id in figure_ids:
        entry = context.figure(figure_id)
        caption = str(entry.get("caption", "")).strip()
        if not caption:
            raise ValueError(f"У иллюстрации {figure_id!r} отсутствует подпись в {context.manifest_path}")
        number = context.figure_number(figure_id)
        story.append(para(f"На рисунке {number} показан экран «{caption}».", "body", context))
        story.extend(figure_flowables(figure_id, context))
    return context


def _wrap_code_line(line: str, max_width: float = CONTENT_WIDTH) -> list[str]:
    line = line.expandtabs(4)
    if not line:
        return [""]
    indent = re.match(r"\s*", line).group(0)
    continuation = indent + "  "
    chunks: list[str] = []
    remaining = line
    first = True
    while remaining:
        prefix = "" if first else continuation
        available = max_width - pdfmetrics.stringWidth(prefix, FONT_MONO, 12)
        current = ""
        for character in remaining:
            if current and pdfmetrics.stringWidth(current + character, FONT_MONO, 12) > available:
                break
            current += character
        if len(current) == len(remaining):
            chunks.append(prefix + remaining)
            break
        split_at = max(current.rfind(" "), current.rfind("/"), current.rfind("-"), current.rfind(":"))
        if split_at > max(0, len(current) // 2):
            split_at += 1
            current = remaining[:split_at].rstrip()
        else:
            split_at = len(current)
        chunks.append(prefix + current)
        remaining = remaining[split_at:].lstrip() if not remaining.startswith(indent) or not first else remaining[split_at:]
        first = False
    return chunks


def code_flowables(lines: Iterable[str]) -> list:
    result = []
    for line in lines:
        for chunk in _wrap_code_line(line):
            result.append(XPreformatted(escape(chunk) if chunk else " ", STYLES["code"]))
    result.append(Spacer(1, 6))
    return result


def _flowable_height(flowable) -> float:
    """Возвращает высоту простого flowable при рабочей ширине документа."""
    _, height = flowable.wrap(CONTENT_WIDTH, PAGE_HEIGHT)
    return height


def _balance_source_end(items: list) -> None:
    """Не оставляет короткий хвост источника один перед внешним PageBreak.

    Сборщики комплекта ставят принудительный разрыв между Markdown-источниками.
    Если последний абзац или пункт занимает не больше шести строк, связываем его
    с предыдущим коротким текстовым блоком. Ограничение на двенадцать строк не даёт
    этому правилу создавать большие пустые области в конце страницы.
    """
    if len(items) < 2 or not isinstance(items[-1], Paragraph) or not isinstance(items[-2], Paragraph):
        return
    tail_height = _flowable_height(items[-1])
    group_height = _flowable_height(items[-2]) + tail_height
    if tail_height <= SOURCE_END_TAIL_HEIGHT and group_height <= SOURCE_END_GROUP_HEIGHT:
        start = len(items) - 2
        if (
            start
            and isinstance(items[start - 1], Paragraph)
            and items[start - 1].style.name in {"h1", "h2", "h3"}
            and items[start - 1].style.keepWithNext
        ):
            start -= 1
        grouped = items[start:]
        del items[start:]
        items.append(KeepTogether(grouped))


def _short_figure_reference(lines: list[str]) -> bool:
    text = " ".join(lines)
    return len(text) <= 300 and bool(FIGURE_REFERENCE.search(text))


def _append_figure_group(items: list, figure_flowables: list) -> None:
    """Связывает короткую ссылку и её заголовок с неделимым рисунком."""
    if len(figure_flowables) != 1 or not isinstance(figure_flowables[0], KeepTogether):
        items.extend(figure_flowables)
        return
    figure_content = list(figure_flowables[0]._content)
    start = len(items)
    if start and isinstance(items[start - 1], Paragraph) and items[start - 1].style.name == "reference":
        start -= 1
    if (
        start
        and isinstance(items[start - 1], Paragraph)
        and items[start - 1].style.name in {"h1", "h2", "h3"}
        and items[start - 1].style.keepWithNext
    ):
        start -= 1
    if start == len(items):
        items.extend(figure_flowables)
        return
    grouped = [*items[start:], *figure_content]
    del items[start:]
    items.append(KeepTogether(grouped))


def markdown(
    path: Path,
    skip_first_h1: bool = True,
    context: GostContext | None = None,
    diagrams: dict[str, tuple[callable, str]] | None = None,
) -> list:
    """Преобразует используемое проектом подмножество Markdown в flowables."""
    context = context or GostContext()
    diagrams = diagrams or {}
    items: list = []
    paragraph_lines: list[str] = []
    list_item: list[str] = []
    table_rows: list[list[str]] = []
    code_lines: list[str] = []
    in_code = False
    first_heading = True
    current_heading = "документа"
    pending_table_id: str | None = None
    pending_table_caption: str | None = None

    def flush_text(*, before_figure: bool = False) -> None:
        if paragraph_lines:
            # Markdown обычно отделяет ссылку на рисунок от marker пустой
            # строкой, поэтому распознаём её при обычном flush, а не только
            # непосредственно в ветке marker.
            kind = "reference" if _short_figure_reference(paragraph_lines) else "body"
            items.append(para(" ".join(paragraph_lines), kind, context))
            paragraph_lines.clear()
        if list_item:
            items.append(Paragraph(escape(_plain(context.resolve_references(list_item[1]))), STYLES["bullet"], bulletText=list_item[0]))
            list_item.clear()

    def flush_table() -> None:
        nonlocal pending_table_id, pending_table_caption
        if not table_rows:
            return
        caption = pending_table_caption or f"Сведения раздела «{current_heading}»"
        items.extend(table_flowables(table_rows.copy(), caption=caption, context=context, table_id=pending_table_id))
        items.append(Spacer(1, 6))
        table_rows.clear()
        pending_table_id = None
        pending_table_caption = None

    for source_line in path.read_text(encoding="utf-8").splitlines():
        stripped = source_line.strip()
        if in_code:
            if stripped.startswith("```"):
                items.extend(code_flowables(code_lines))
                code_lines.clear()
                in_code = False
            else:
                code_lines.append(source_line)
            continue
        if stripped.startswith("```"):
            flush_text()
            flush_table()
            in_code = True
            continue
        if stripped.startswith("|"):
            flush_text()
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if not all(re.fullmatch(r":?-+:?", cell) for cell in cells):
                table_rows.append(cells)
            continue
        flush_table()
        if not stripped:
            flush_text()
            continue
        figure_marker = FIGURE_MARKER.fullmatch(stripped)
        if figure_marker:
            flush_text(before_figure=True)
            figure_id = figure_marker.group(1)
            if figure_id in diagrams:
                factory, caption = diagrams[figure_id]
                _append_figure_group(items, drawing_flowables(factory(), caption, figure_id, context))
            else:
                _append_figure_group(items, figure_flowables(figure_id, context))
            continue
        table_marker = TABLE_MARKER.fullmatch(stripped)
        if table_marker:
            flush_text()
            pending_table_id = table_marker.group("id")
            pending_table_caption = table_marker.group("caption") or None
            continue
        image = IMAGE.fullmatch(stripped)
        if image:
            flush_text(before_figure=True)
            caption, image_path = image.groups()
            figure_id = "image-" + re.sub(r"[^\w.-]+", "-", image_path).strip("-")
            _append_figure_group(
                items,
                figure_flowables(figure_id, context, path=image_path, caption=caption or None, source=image_path),
            )
            continue
        if stripped.startswith("<!--"):
            flush_text(before_figure=True)
            legacy = re.fullmatch(r"<!--\s*([\w.-]+)\s*-->", stripped)
            if legacy and legacy.group(1) in diagrams:
                figure_id = legacy.group(1)
                factory, caption = diagrams[figure_id]
                _append_figure_group(items, drawing_flowables(factory(), caption, figure_id, context))
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", source_line)
        if heading:
            flush_text()
            level, heading_text = len(heading.group(1)), heading.group(2)
            current_heading = _plain(heading_text)
            if level == 1 and first_heading and skip_first_h1:
                first_heading = False
                continue
            first_heading = False
            items.append(para(heading_text, f"h{level}", context))
            continue
        bulleted = re.match(r"^\s*[-*]\s+(.+)$", source_line)
        if bulleted:
            flush_text()
            list_item.extend(["•", bulleted.group(1)])
            continue
        numbered = re.match(r"^(\d+)\.\s+(.+)$", source_line)
        if numbered:
            flush_text()
            list_item.extend([numbered.group(1) + ".", numbered.group(2)])
            continue
        if list_item:
            list_item[1] += " " + stripped
        else:
            paragraph_lines.append(stripped)

    if in_code:
        raise ValueError(f"Незакрытый блок кода: {path}")
    flush_text()
    flush_table()
    _balance_source_end(items)
    return items


def draw_page_number(canvas, document, *, skip_first: bool) -> None:
    if skip_first and document.page == 1:
        return
    canvas.saveState()
    canvas.setFillColor(BLACK)
    canvas.setFont(FONT_REGULAR, 12)
    canvas.drawCentredString(PAGE_WIDTH / 2, 10 * mm, str(document.page))
    canvas.restoreState()


def page_number_after_title(canvas, document) -> None:
    draw_page_number(canvas, document, skip_first=True)


def page_number_all(canvas, document) -> None:
    draw_page_number(canvas, document, skip_first=False)


class GostDocTemplate(SimpleDocTemplate):
    """SimpleDocTemplate без скрытх внутренних отступов Frame.

    Штатные 6 pt с каждой стороны меняют фактические поля и заставляют
    таблицы и схемы полной ширины выходить за правое поле.
    """

    def build(
        self,
        flowables,
        onFirstPage=_doNothing,
        onLaterPages=_doNothing,
        canvasmaker=pdf_canvas.Canvas,
    ):
        self._calc()
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
            id="normal",
        )
        self.addPageTemplates(
            [
                PageTemplate(id="First", frames=frame, onPage=onFirstPage, pagesize=self.pagesize),
                PageTemplate(id="Later", frames=frame, onPage=onLaterPages, pagesize=self.pagesize),
            ]
        )
        if onFirstPage is _doNothing and hasattr(self, "onFirstPage"):
            self.pageTemplates[0].beforeDrawPage = self.onFirstPage
        if onLaterPages is _doNothing and hasattr(self, "onLaterPages"):
            self.pageTemplates[1].beforeDrawPage = self.onLaterPages
        BaseDocTemplate.build(self, flowables, canvasmaker=canvasmaker)


def gost_document(output: Path, *, title: str, author: str) -> SimpleDocTemplate:
    output.parent.mkdir(parents=True, exist_ok=True)
    return GostDocTemplate(
        str(output),
        invariant=1,
        pageCompression=1,
        pagesize=A4,
        leftMargin=LEFT_MARGIN,
        rightMargin=RIGHT_MARGIN,
        topMargin=TOP_MARGIN,
        bottomMargin=BOTTOM_MARGIN,
        title=title,
        author=author,
    )

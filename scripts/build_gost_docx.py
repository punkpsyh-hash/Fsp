"""Собрать редактируемые Word-документы из актуальных Markdown проекта.

Генератор не меняет исходный текст: он переносит заголовки, абзацы, списки,
таблицы и блоки кода в DOCX, добавляя только навигацию и подписи иллюстраций.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
from html import unescape
import json
from pathlib import Path
import re
import sys
from typing import Iterable, Sequence

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.shared import Cm, Mm, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "docs" / "delivery" / "gost"
DEFAULT_MANIFEST = ROOT / "docs" / "assets" / "screenshots" / "manifest.json"
DEFAULT_DOCUMENT_SET = ROOT / "docs" / "document-set.json"
BLACK = RGBColor(0, 0, 0)
FONT = "Times New Roman"
CONTENT_WIDTH_CM = 16.5
MAX_FIGURE_HEIGHT_CM = 21.5

INLINE_TOKEN = re.compile(
    r"(!?\[[^\]]*\]\([^)]*\)|`[^`]*`|\*\*[^*]+\*\*|__[^_]+__|(?<!\*)\*[^*]+\*(?!\*)|(?<!_)_[^_]+_(?!_))"
)
LINK = re.compile(r"^\[([^\]]+)\]\(([^)]+)\)$")
IMAGE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)$")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
LIST_ITEM = re.compile(r"^(\s*)([-+*]|\d+[.)])\s+(.+)$")
NUMBER_PREFIX = re.compile(r"^(\d+(?:\.\d+)*)(?:[.)])?\s+(.+)$")
FIGURE_MARKER = re.compile(r"^<!--\s*figure:([A-Za-z0-9_.-]+)\s*-->$")
LEGACY_FIGURE_MARKER = re.compile(r"^<!--\s*(diagram_[A-Za-z0-9_.-]+)\s*-->$")
FIGURE_REFERENCE = re.compile(r"\[\[figure:([A-Za-z0-9_.-]+)\]\]")
HTML_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Block:
    kind: str
    text: str = ""
    level: int = 0
    rows: tuple[tuple[str, ...], ...] = ()
    marker: str = ""
    target: str = ""


@dataclass(frozen=True)
class Figure:
    identifier: str
    path: Path
    caption: str
    source_note: str
    bound_sources: tuple[str, ...] = ()
    digest: str = ""

    def matches(self, source: Path) -> bool:
        relative = source.relative_to(ROOT).as_posix().lower()
        names = {relative, source.name.lower(), source.stem.lower()}
        return any(item.replace("\\", "/").strip().lower() in names for item in self.bound_sources)


@dataclass(frozen=True)
class DocumentSpec:
    key: str
    filename: str
    title: str
    sources: tuple[Path, ...]
    navigation: bool = False


def _source_path(value: object, *, root: Path, manifest: Path) -> Path:
    """Проверить один явно опубликованный Markdown-источник из manifest."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{manifest}: путь источника должен быть непустой строкой")
    raw = value.strip()
    if "\\" in raw or any(char in raw for char in "*?["):
        raise ValueError(f"{manifest}: путь источника должен быть явным POSIX-путём: {raw}")
    relative = Path(raw)
    if relative.is_absolute() or relative.suffix.lower() != ".md":
        raise ValueError(f"{manifest}: источник должен быть относительным Markdown-файлом: {raw}")
    candidate = (root / relative).resolve()
    docs_root = (root / "docs").resolve()
    try:
        candidate.relative_to(docs_root)
    except ValueError as error:
        raise ValueError(f"{manifest}: источник должен находиться внутри docs/: {raw}") from error
    if not candidate.is_file():
        raise FileNotFoundError(f"{manifest}: источник не найден: {raw}")
    return candidate


def _source_list(values: object, *, root: Path, manifest: Path, field: str) -> tuple[Path, ...]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"{manifest}: {field} должен быть непустым массивом")
    result = tuple(_source_path(value, root=root, manifest=manifest) for value in values)
    if len(result) != len(set(result)):
        raise ValueError(f"{manifest}: {field} содержит повторяющиеся источники")
    return result


def document_specs(path: Path = DEFAULT_DOCUMENT_SET, *, root: Path = ROOT) -> tuple[DocumentSpec, ...]:
    """Загрузить единственный управляемый состав семи публикуемых документов."""
    if not path.is_file():
        raise FileNotFoundError(f"Манифест письменного комплекта не найден: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: ожидается JSON-объект")
    published = _source_list(
        payload.get("published_sources"), root=root, manifest=path, field="published_sources"
    )
    published_set = set(published)
    formatting_source = _source_path(payload.get("formatting_source"), root=root, manifest=path)
    if formatting_source not in published_set:
        raise ValueError(f"{path}: formatting_source должен входить в published_sources")
    raw_documents = payload.get("documents")
    if not isinstance(raw_documents, list):
        raise ValueError(f"{path}: ожидается массив documents")
    specs: list[DocumentSpec] = []
    seen: set[str] = set()
    for raw in raw_documents:
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: каждый элемент documents должен быть объектом")
        key = str(raw.get("id", "")).strip()
        title = str(raw.get("title", "")).strip()
        if not key or not title:
            raise ValueError(f"{path}: каждый документ требует id, title и непустой sources")
        if key in seen:
            raise ValueError(f"{path}: повторяющийся id документа {key}")
        seen.add(key)
        filename = str(raw.get("filename", f"{key}.docx")).strip()
        if Path(filename).name != filename or not filename.lower().endswith(".docx"):
            raise ValueError(f"{path}: filename должен быть именем DOCX без каталога: {filename}")
        sources = _source_list(
            raw.get("sources"), root=root, manifest=path, field=f"documents[{key}].sources"
        )
        unpublished = [
            source.relative_to(root).as_posix()
            for source in sources
            if source not in published_set
        ]
        if unpublished:
            raise ValueError(f"{path}: {key} содержит неопубликованные источники: {unpublished}")
        if key == "all-documents" and sources != published:
            expected_names = [item.relative_to(root).as_posix() for item in published]
            actual_names = [item.relative_to(root).as_posix() for item in sources]
            raise ValueError(
                f"{path}: all-documents.sources должен точно повторять published_sources; "
                f"ожидалось {expected_names}, получено {actual_names}"
            )
        specs.append(DocumentSpec(
            key, filename, title, sources,
            navigation=bool(raw.get("navigation", key == "all-documents")),
        ))
    required = {
        "self-deployment-guide", "release-guide", "api-guide", "documentation",
        "technical-report", "project-report", "all-documents",
    }
    if seen != required:
        missing = sorted(required - seen)
        extra = sorted(seen - required)
        raise ValueError(f"{path}: ожидаются ровно семь документов; отсутствуют {missing}, лишние {extra}")
    return tuple(specs)


def _manifest_entries(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        raise ValueError("Манифест иллюстраций должен быть массивом или объектом")
    for key in ("figures", "images", "screenshots", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    entries: list[dict[str, object]] = []
    for identifier, value in payload.items():
        if isinstance(value, dict):
            entries.append({"id": identifier, **value})
    return entries


def load_figures(path: Path = DEFAULT_MANIFEST) -> tuple[Figure, ...]:
    if not path.exists():
        print(f"Предупреждение: манифест иллюстраций не найден: {path}", file=sys.stderr)
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    result: list[Figure] = []
    seen: set[str] = set()
    for raw in _manifest_entries(payload):
        identifier = str(raw.get("id", "")).strip()
        caption = str(raw.get("caption", "")).strip()
        raw_path = str(raw.get("path", "")).strip()
        if not identifier or not caption or not raw_path:
            raise ValueError("Каждая иллюстрация требует id, path и caption")
        if identifier in seen:
            raise ValueError(f"Повторяющийся id иллюстрации: {identifier}")
        seen.add(identifier)
        figure_path = Path(raw_path)
        if not figure_path.is_absolute():
            figure_path = ROOT / figure_path
        if not figure_path.is_file():
            raise FileNotFoundError(f"Файл иллюстрации {identifier} не найден: {figure_path}")
        source_note = str(raw.get("source", "")).strip()
        source_bindings = raw.get("sources", ())
        if isinstance(source_bindings, str):
            bound_sources = (source_bindings,)
        elif isinstance(source_bindings, list):
            bound_sources = tuple(str(item) for item in source_bindings)
        else:
            raise ValueError(f"Поле sources иллюстрации {identifier} должно быть строкой или массивом")
        digest = str(raw.get("sha256", "")).strip().lower()
        if digest:
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError(f"Некорректный SHA-256 иллюстрации {identifier}")
            actual = sha256(figure_path.read_bytes()).hexdigest()
            if actual != digest:
                raise ValueError(f"SHA-256 иллюстрации {identifier} не совпадает: {actual}")
        result.append(Figure(identifier, figure_path, caption, source_note, bound_sources, digest))
    return tuple(result)


def _split_table_row(line: str) -> tuple[str, ...]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    in_code = False
    for char in text:
        if escaped:
            if char in {"|", "\\"}:
                current.append(char)
            else:
                current.extend(("\\", char))
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "`":
            in_code = not in_code
            current.append(char)
        elif char == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    cells.append("".join(current).strip())
    return tuple(cells)


def _is_separator(row: Sequence[str]) -> bool:
    return bool(row) and all(re.fullmatch(r":?-{3,}:?", item.replace(" ", "")) for item in row)


def parse_markdown_text(text: str) -> list[Block]:
    """Разобрать используемое в docs подмножество Markdown без потери блоков кода."""
    lines = text.splitlines()
    blocks: list[Block] = []
    paragraph: list[str] = []
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(Block("paragraph", " ".join(item.strip() for item in paragraph).strip()))
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            flush_paragraph()
            fence = stripped[:3]
            code: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(fence):
                code.append(lines[index])
                index += 1
            blocks.append(Block("code", "\n".join(code)))
            index += 1
            continue
        if not stripped:
            flush_paragraph()
            index += 1
            continue
        marker = FIGURE_MARKER.fullmatch(stripped) or LEGACY_FIGURE_MARKER.fullmatch(stripped)
        if marker:
            flush_paragraph()
            blocks.append(Block("figure", target=marker.group(1)))
            index += 1
            continue
        if stripped.startswith("<!--"):
            flush_paragraph()
            while index < len(lines) and "-->" not in lines[index]:
                index += 1
            index += 1
            continue
        heading = HEADING.match(line)
        if heading:
            flush_paragraph()
            blocks.append(Block("heading", heading.group(2), len(heading.group(1))))
            index += 1
            continue
        image = IMAGE.fullmatch(stripped)
        if image:
            flush_paragraph()
            blocks.append(Block("image", image.group(1), target=image.group(2)))
            index += 1
            continue
        if line.lstrip().startswith("|"):
            flush_paragraph()
            raw_rows: list[tuple[str, ...]] = []
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                raw_rows.append(_split_table_row(lines[index]))
                index += 1
            rows = tuple(row for row in raw_rows if not _is_separator(row))
            if rows:
                blocks.append(Block("table", rows=rows))
            continue
        item = LIST_ITEM.match(line)
        if item:
            flush_paragraph()
            indent = len(item.group(1).expandtabs(4)) // 2
            marker_text = item.group(2)
            body = [item.group(3).strip()]
            index += 1
            while index < len(lines):
                continuation = lines[index]
                if not continuation.strip():
                    break
                if HEADING.match(continuation) or LIST_ITEM.match(continuation) or continuation.lstrip().startswith("|"):
                    break
                if continuation.strip().startswith(("```", "~~~", "<!--")):
                    break
                body.append(continuation.strip())
                index += 1
            blocks.append(Block("list", " ".join(body), indent, marker=marker_text))
            continue
        if stripped.startswith(">"):
            flush_paragraph()
            quote: list[str] = []
            while index < len(lines) and lines[index].lstrip().startswith(">"):
                quote.append(lines[index].lstrip()[1:].strip())
                index += 1
            blocks.append(Block("quote", " ".join(quote)))
            continue
        if line.startswith("    ") or line.startswith("\t"):
            flush_paragraph()
            code = []
            while index < len(lines) and (lines[index].startswith("    ") or lines[index].startswith("\t")):
                value = lines[index][4:] if lines[index].startswith("    ") else lines[index][1:]
                code.append(value)
                index += 1
            blocks.append(Block("code", "\n".join(code)))
            continue
        if re.fullmatch(r"\s*(?:-{3,}|_{3,}|\*{3,})\s*", line):
            flush_paragraph()
            index += 1
            continue
        paragraph.append(line)
        index += 1
    flush_paragraph()
    return blocks


def parse_markdown(path: Path) -> list[Block]:
    return parse_markdown_text(path.read_text(encoding="utf-8"))


class HeadingNumberer:
    """Дополнить только ненумерованные заголовки, сохранив номера источника."""

    def __init__(self, blocks: Sequence[Block], source_number: str):
        self.source_number = source_number
        self.has_explicit_h2 = any(
            block.kind == "heading" and block.level == 2 and NUMBER_PREFIX.match(_plain(block.text))
            for block in blocks
        )
        self.seen_explicit_h2 = False
        self.h2 = 0
        self.preface = 0
        self.current: dict[int, str] = {1: source_number}
        self.child_count: dict[int, int] = {}

    def number(self, level: int, text: str) -> str:
        clean = _plain(text)
        explicit = NUMBER_PREFIX.match(clean)
        if level == 1:
            body = explicit.group(2) if explicit else clean
            self.current = {1: self.source_number}
            self.child_count.clear()
            return f"{self.source_number}. {body}"
        if explicit:
            number = explicit.group(1)
            self.current[level] = number
            for deeper in range(level + 1, 7):
                self.current.pop(deeper, None)
            if level == 2:
                self.seen_explicit_h2 = True
                try:
                    self.h2 = max(self.h2, int(number.split(".")[0]))
                except ValueError:
                    pass
            return clean
        if level == 2:
            if self.has_explicit_h2 and not self.seen_explicit_h2:
                return clean
            else:
                self.h2 += 1
                number = str(self.h2)
            self.current = {1: self.source_number, 2: number}
            self.child_count.clear()
        else:
            parent = self.current.get(level - 1, "0")
            count = self.child_count.get(level, 0) + 1
            self.child_count[level] = count
            number = f"{parent}.{count}"
            self.current[level] = number
            for deeper in range(level + 1, 7):
                self.current.pop(deeper, None)
                self.child_count.pop(deeper, None)
        return f"{number}. {clean}"


def _plain(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("`", "").replace("**", "").replace("__", "")
    text = HTML_TAG.sub("", text)
    return unescape(text).strip()


def _set_rfonts(rpr: OxmlElement, name: str = FONT) -> None:
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for key in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn(f"w:{key}"), name)


def _format_run(run, size: float | None = None, bold: bool | None = None, italic: bool | None = None) -> None:
    run.font.name = FONT
    run.font.color.rgb = BLACK
    run.font.underline = False
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    rpr = run._element.get_or_add_rPr()
    _set_rfonts(rpr)
    color = rpr.find(qn("w:color"))
    if color is None:
        color = OxmlElement("w:color")
        rpr.append(color)
    color.set(qn("w:val"), "000000")


def _add_hyperlink(paragraph, label: str, target: str, *, anchor: bool = False) -> None:
    hyperlink = OxmlElement("w:hyperlink")
    if anchor:
        hyperlink.set(qn("w:anchor"), target)
        hyperlink.set(qn("w:history"), "1")
    else:
        rel = paragraph.part.relate_to(target, RT.HYPERLINK, is_external=True)
        hyperlink.set(qn("r:id"), rel)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    _set_rfonts(rpr)
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "000000")
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "none")
    rpr.extend((color, underline))
    run.append(rpr)
    text = OxmlElement("w:t")
    text.set(qn("xml:space"), "preserve")
    text.text = _plain(label)
    run.append(text)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _target_bookmark(target: str, source: Path, bookmarks: dict[str, str]) -> str | None:
    if target.startswith("#"):
        return None
    clean = target.split("#", 1)[0]
    if not clean.lower().endswith(".md"):
        return None
    resolved = (source.parent / clean).resolve()
    return bookmarks.get(resolved.as_posix().lower())


def add_inline(
    paragraph,
    text: str,
    source: Path,
    bookmarks: dict[str, str],
    *,
    size: float | None = None,
    figure_refs: dict[str, int] | None = None,
) -> None:
    if figure_refs:
        text = FIGURE_REFERENCE.sub(
            lambda match: f"рисунке {figure_refs[match.group(1)]}"
            if match.group(1) in figure_refs else match.group(0),
            text,
        )
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    position = 0
    for match in INLINE_TOKEN.finditer(text):
        if match.start() > position:
            run = paragraph.add_run(unescape(HTML_TAG.sub("", text[position:match.start()])))
            _format_run(run, size)
        token = match.group(0)
        link = LINK.match(token)
        if link and not token.startswith("!"):
            bookmark = _target_bookmark(link.group(2), source, bookmarks)
            _add_hyperlink(paragraph, link.group(1), bookmark or link.group(2), anchor=bookmark is not None)
        elif token.startswith("`"):
            run = paragraph.add_run(token[1:-1])
            _format_run(run, size)
        elif token.startswith(("**", "__")):
            run = paragraph.add_run(token[2:-2])
            _format_run(run, size, bold=True)
        else:
            run = paragraph.add_run(token[1:-1])
            _format_run(run, size, italic=True)
        position = match.end()
    if position < len(text):
        run = paragraph.add_run(unescape(HTML_TAG.sub("", text[position:])))
        _format_run(run, size)


def _style_font(style, size: float, *, bold: bool = False, italic: bool = False) -> None:
    style.font.name = FONT
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.italic = italic
    style.font.color.rgb = BLACK
    style.font.underline = False
    rpr = style.element.get_or_add_rPr()
    _set_rfonts(rpr)
    color = rpr.find(qn("w:color"))
    if color is None:
        color = OxmlElement("w:color")
        rpr.append(color)
    color.set(qn("w:val"), "000000")
    for attribute in ("themeColor", "themeTint", "themeShade"):
        color.attrib.pop(qn(f"w:{attribute}"), None)


def _blacken_style_tree(styles) -> None:
    """Удалить цвет темы и подчёркивание даже из неиспользуемых встроенных стилей."""
    for style in styles:
        if not hasattr(style, "font"):
            continue
        style.font.name = FONT
        style.font.color.rgb = BLACK
        style.font.underline = False
    for fonts in styles.element.iter(qn("w:rFonts")):
        for key in ("ascii", "hAnsi", "eastAsia", "cs"):
            fonts.set(qn(f"w:{key}"), FONT)
        for key in list(fonts.attrib):
            if "theme" in key.lower():
                fonts.attrib.pop(key, None)
    for color in styles.element.iter(qn("w:color")):
        color.set(qn("w:val"), "000000")
        for key in list(color.attrib):
            if "theme" in key.lower():
                color.attrib.pop(key, None)
    for underline in styles.element.iter(qn("w:u")):
        underline.set(qn("w:val"), "none")
    # Цвет рамок хранится не в w:color, а в атрибуте w:color самих
    # w:top/w:bottom/...; встроенные стили шаблона используют accent1.
    for element in styles.element.iter():
        for key in list(element.attrib):
            local_name = key.rsplit("}", 1)[-1]
            if local_name == "color":
                element.set(key, "000000")
            elif local_name in {"themeColor", "themeTint", "themeShade"}:
                element.attrib.pop(key, None)


def _configure_styles(document: Document) -> None:
    styles = document.styles
    _blacken_style_tree(styles)
    _style_font(styles["Default Paragraph Font"], 14)
    _style_font(styles["Normal"], 14)
    normal = styles["Normal"].paragraph_format
    normal.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    normal.first_line_indent = Cm(1.25)
    normal.line_spacing = 1.5
    normal.space_before = Pt(0)
    normal.space_after = Pt(0)

    _style_font(styles["Title"], 14, bold=True)
    title = styles["Title"].paragraph_format
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.first_line_indent = Cm(0)
    title.line_spacing = 1.5
    title.space_before = Pt(0)
    title.space_after = Pt(18)
    title_properties = styles["Title"].element.get_or_add_pPr()
    title_border = title_properties.find(qn("w:pBdr"))
    if title_border is not None:
        title_properties.remove(title_border)

    for level in range(1, 5):
        style = styles[f"Heading {level}"]
        _style_font(style, 14, bold=True)
        fmt = style.paragraph_format
        fmt.alignment = WD_ALIGN_PARAGRAPH.CENTER if level == 1 else WD_ALIGN_PARAGRAPH.LEFT
        fmt.first_line_indent = Cm(0)
        fmt.left_indent = Cm(0)
        fmt.line_spacing = 1.5
        fmt.space_before = Pt(12 if level <= 2 else 6)
        fmt.space_after = Pt(6)
        fmt.keep_with_next = True

    custom = {
        "GOST List": (14, False, False),
        "GOST Quote": (14, False, True),
        "GOST Code": (12, False, False),
        "GOST Caption": (12, False, False),
        "GOST Figure Source": (12, False, False),
        "GOST Figure Reference": (14, False, False),
        "GOST Table Caption": (12, False, False),
        "GOST Table Reference": (14, False, False),
        "GOST Cover Metadata": (14, False, False),
        "GOST Navigation": (14, False, False),
    }
    for name, (size, bold, italic) in custom.items():
        style = styles[name] if name in styles else styles.add_style(name, 1)
        _style_font(style, size, bold=bold, italic=italic)
        fmt = style.paragraph_format
        fmt.space_before = Pt(0)
        fmt.space_after = Pt(0)
        fmt.line_spacing = 1.5
    styles["GOST List"].paragraph_format.first_line_indent = Cm(-0.63)
    styles["GOST List"].paragraph_format.left_indent = Cm(1.25)
    styles["GOST List"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    styles["GOST Quote"].paragraph_format.left_indent = Cm(1.25)
    styles["GOST Quote"].paragraph_format.first_line_indent = Cm(0)
    styles["GOST Quote"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    styles["GOST Code"].paragraph_format.left_indent = Cm(1.25)
    styles["GOST Code"].paragraph_format.first_line_indent = Cm(0)
    styles["GOST Code"].paragraph_format.line_spacing = 1.0
    styles["GOST Code"].paragraph_format.space_before = Pt(3)
    styles["GOST Code"].paragraph_format.space_after = Pt(3)
    styles["GOST Caption"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    styles["GOST Caption"].paragraph_format.first_line_indent = Cm(0)
    styles["GOST Caption"].paragraph_format.line_spacing = 1.0
    styles["GOST Figure Source"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    styles["GOST Figure Source"].paragraph_format.first_line_indent = Cm(0)
    styles["GOST Figure Source"].paragraph_format.line_spacing = 1.0
    styles["GOST Figure Reference"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    styles["GOST Figure Reference"].paragraph_format.first_line_indent = Cm(1.25)
    styles["GOST Figure Reference"].paragraph_format.keep_with_next = True
    styles["GOST Table Caption"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    styles["GOST Table Caption"].paragraph_format.first_line_indent = Cm(0)
    styles["GOST Table Caption"].paragraph_format.line_spacing = 1.0
    styles["GOST Table Caption"].paragraph_format.keep_with_next = True
    styles["GOST Table Reference"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    styles["GOST Table Reference"].paragraph_format.first_line_indent = Cm(1.25)
    styles["GOST Table Reference"].paragraph_format.keep_with_next = True
    styles["GOST Cover Metadata"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    styles["GOST Cover Metadata"].paragraph_format.first_line_indent = Cm(0)
    styles["GOST Cover Metadata"].paragraph_format.line_spacing = 1.5
    styles["GOST Cover Metadata"].paragraph_format.space_after = Pt(6)
    styles["GOST Navigation"].paragraph_format.first_line_indent = Cm(0)
    styles["GOST Navigation"].paragraph_format.line_spacing = 1.0
    styles["GOST Navigation"].paragraph_format.space_after = Pt(3)


def _page_field(paragraph) -> None:
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = " PAGE "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    shown = OxmlElement("w:t")
    shown.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend((begin, instruction, separate, shown, end))
    _format_run(run, 12)


def _configure_page_geometry(section) -> None:
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.left_margin = Mm(30)
    section.right_margin = Mm(15)
    section.top_margin = Mm(20)
    section.bottom_margin = Mm(20)
    section.footer_distance = Mm(10)


def _configure_document(document: Document, title: str) -> None:
    """Configure the independent, unnumbered cover section."""
    section = document.sections[0]
    section.start_type = WD_SECTION.NEW_PAGE
    section.different_first_page_header_footer = False
    _configure_page_geometry(section)
    section.footer.is_linked_to_previous = False
    cover_footer = section.footer.paragraphs[0]
    cover_footer.text = ""
    for run in list(cover_footer.runs):
        cover_footer._p.remove(run._r)
    settings = document.settings.element
    update = settings.find(qn("w:updateFields"))
    if update is None:
        update = OxmlElement("w:updateFields")
        settings.append(update)
    update.set(qn("w:val"), "true")
    properties = document.core_properties
    properties.title = title
    properties.author = ""
    properties.last_modified_by = ""
    _configure_styles(document)


def _add_body_section(document: Document) -> None:
    """Start the body on page 2 with an independent numbered footer."""
    section = document.add_section(WD_SECTION.NEW_PAGE)
    section.start_type = WD_SECTION.NEW_PAGE
    section.different_first_page_header_footer = False
    _configure_page_geometry(section)
    section.footer.is_linked_to_previous = False
    footer = section.footer.paragraphs[0]
    footer.text = ""
    for run in list(footer.runs):
        footer._p.remove(run._r)
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.paragraph_format.first_line_indent = Cm(0)
    _page_field(footer)
    page_numbering = section._sectPr.find(qn("w:pgNumType"))
    if page_numbering is None:
        page_numbering = OxmlElement("w:pgNumType")
        section._sectPr.append(page_numbering)
    page_numbering.set(qn("w:start"), "2")


def _bookmark(paragraph, name: str, bookmark_id: int) -> None:
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(bookmark_id))
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(bookmark_id))
    paragraph._p.insert(1 if paragraph._p.pPr is not None else 0, start)
    paragraph._p.append(end)


def _source_bookmarks(sources: Iterable[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for source in sources:
        number = source.name[:2]
        result[source.resolve().as_posix().lower()] = f"doc_{number}"
    return result


def _source_title(source: Path, blocks: Sequence[Block]) -> str:
    for block in blocks:
        if block.kind == "heading" and block.level == 1:
            return HeadingNumberer(blocks, source.name[:2]).number(1, block.text)
    return f"{source.name[:2]}. {source.stem[3:].replace('-', ' ').strip()}"


def _repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    marker = OxmlElement("w:tblHeader")
    marker.set(qn("w:val"), "true")
    tr_pr.append(marker)


def _cant_split(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    marker = OxmlElement("w:cantSplit")
    tr_pr.append(marker)


def _set_cell_width(cell, width_cm: float) -> None:
    cell.width = Cm(width_cm)
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.find(qn("w:tcW"))
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(Cm(width_cm).twips))
    tc_w.set(qn("w:type"), "dxa")


def _table_title(current_heading: str, rows: Sequence[Sequence[str]]) -> str:
    heading = _plain(current_heading)
    numbered = NUMBER_PREFIX.match(heading)
    if numbered:
        heading = numbered.group(2)
    if heading:
        return heading[:140].rstrip(" .:;—-")
    labels = [_plain(item) for item in rows[0] if _plain(item)]
    return ("Перечень " + ", ".join(labels[:3])).rstrip(" .:;—-")


def add_table(
    document: Document,
    rows: Sequence[Sequence[str]],
    source: Path,
    bookmarks: dict[str, str],
    number: int,
    current_heading: str,
    figure_refs: dict[str, int] | None = None,
) -> None:
    reference = document.add_paragraph(style="GOST Table Reference")
    run = reference.add_run(f"Сведения приведены в таблице {number}.")
    _format_run(run, 14)
    caption = document.add_paragraph(style="GOST Table Caption")
    run = caption.add_run(f"Таблица {number} — {_table_title(current_heading, rows)}")
    _format_run(run, 12)
    columns = max(len(row) for row in rows)
    normalized = [list(row) + [""] * (columns - len(row)) for row in rows]
    weights = [max(8, min(48, max(len(_plain(row[index])) for row in normalized))) for index in range(columns)]
    total = sum(weights)
    widths = [CONTENT_WIDTH_CM * weight / total for weight in weights]
    table = document.add_table(rows=len(normalized), cols=columns)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table.style = "Table Grid"
    for row_index, row in enumerate(normalized):
        _cant_split(table.rows[row_index])
        if row_index == 0:
            _repeat_table_header(table.rows[row_index])
        for column_index, value in enumerate(row):
            cell = table.cell(row_index, column_index)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            _set_cell_width(cell, widths[column_index])
            paragraph = cell.paragraphs[0]
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
            paragraph.paragraph_format.first_line_indent = Cm(0)
            paragraph.paragraph_format.line_spacing = 1.0
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(0)
            add_inline(paragraph, value, source, bookmarks, size=12, figure_refs=figure_refs)
            if row_index == 0:
                for run in paragraph.runs:
                    run.bold = True
            shading = cell._tc.get_or_add_tcPr().find(qn("w:shd"))
            if shading is not None:
                shading.set(qn("w:fill"), "FFFFFF")
    after = document.add_paragraph()
    after.paragraph_format.space_after = Pt(0)
    after.paragraph_format.first_line_indent = Cm(0)


def _set_picture_alt(shape, identifier: str, caption: str) -> None:
    doc_pr = shape._inline.docPr
    doc_pr.set("name", identifier)
    doc_pr.set("descr", caption)


def add_figure(document: Document, figure: Figure, number: int, *, add_reference: bool = True) -> None:
    if add_reference:
        reference = document.add_paragraph(style="GOST Figure Reference")
        run = reference.add_run(
            f"Материал «{figure.caption.rstrip('.')}» приведён на рисунке\u00a0{number}."
        )
        _format_run(run, 14)
    picture_paragraph = document.add_paragraph()
    picture_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    picture_paragraph.paragraph_format.first_line_indent = Cm(0)
    picture_paragraph.paragraph_format.keep_with_next = True
    try:
        shape = picture_paragraph.add_run().add_picture(str(figure.path))
    except Exception as error:
        raise RuntimeError(f"Не удалось вставить иллюстрацию {figure.identifier}: {figure.path}") from error
    max_width = Cm(CONTENT_WIDTH_CM)
    max_height = Cm(MAX_FIGURE_HEIGHT_CM)
    scale = min(1.0, max_width / shape.width, max_height / shape.height)
    shape.width = int(shape.width * scale)
    shape.height = int(shape.height * scale)
    _set_picture_alt(shape, figure.identifier, figure.caption)
    caption = document.add_paragraph(style="GOST Caption")
    run = caption.add_run(f"Рисунок {number} — {figure.caption.rstrip('.')}" )
    _format_run(run, 12)
    if figure.source_note:
        caption.paragraph_format.keep_with_next = True
        source = document.add_paragraph(style="GOST Figure Source")
        run = source.add_run(f"Источник: {figure.source_note.rstrip('.')}.")
        _format_run(run, 12)


def _add_markdown_image(document: Document, source: Path, block: Block, number: int) -> None:
    target = block.target.split(maxsplit=1)[0].strip("<>")
    image_path = (source.parent / target).resolve()
    if not image_path.is_file():
        raise FileNotFoundError(f"Иллюстрация Markdown не найдена: {image_path}")
    add_figure(document, Figure(f"markdown-{number}", image_path, block.text or image_path.stem, ""), number)


def _add_navigation(document: Document, spec: DocumentSpec, parsed: dict[Path, list[Block]], bookmarks: dict[str, str]) -> None:
    heading = document.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    heading.paragraph_format.first_line_indent = Cm(0)
    run = heading.add_run("Навигация по документам")
    _format_run(run, 14, bold=True)
    note = document.add_paragraph()
    note.add_run(
        "Комплект объединяет текущие и исторические документы. Указанные в источниках даты, "
        "статусы и ограничения сохранены."
    )
    for source in spec.sources:
        paragraph = document.add_paragraph(style="GOST Navigation")
        bookmark = bookmarks[source.resolve().as_posix().lower()]
        _add_hyperlink(paragraph, _source_title(source, parsed[source]), bookmark, anchor=True)


def _blocks_for_source(
    document: Document,
    source: Path,
    blocks: Sequence[Block],
    bookmarks: dict[str, str],
    figures: Sequence[Figure],
    used_figures: set[str],
    figure_numbers: dict[str, int],
    figure_number: int,
    table_number: int,
    bookmark_id: int,
) -> tuple[int, int, int]:
    numberer = HeadingNumberer(blocks, source.name[:2])
    first_heading = True
    current_heading = ""
    figures_by_id = {figure.identifier: figure for figure in figures}
    predicted = figure_number
    figure_refs = dict(figure_numbers)
    for block in blocks:
        if block.kind != "figure":
            continue
        if block.target not in figures_by_id:
            raise ValueError(f"Маркер figure:{block.target} не найден в манифесте")
        if block.target not in figure_refs:
            predicted += 1
            figure_refs[block.target] = predicted
    referenced_ids = {
        match.group(1)
        for block in blocks
        for match in FIGURE_REFERENCE.finditer(block.text)
    }
    for block in blocks:
        if block.kind == "heading":
            current_heading = block.text
            level = min(block.level, 4)
            paragraph = document.add_paragraph(style=f"Heading {level}")
            add_inline(
                paragraph, numberer.number(block.level, block.text), source, bookmarks,
                figure_refs=figure_refs,
            )
            if first_heading and block.level == 1:
                _bookmark(paragraph, bookmarks[source.resolve().as_posix().lower()], bookmark_id)
                bookmark_id += 1
                first_heading = False
        elif block.kind == "paragraph":
            paragraph = document.add_paragraph()
            add_inline(paragraph, block.text, source, bookmarks, figure_refs=figure_refs)
        elif block.kind == "quote":
            paragraph = document.add_paragraph(style="GOST Quote")
            add_inline(paragraph, block.text, source, bookmarks, figure_refs=figure_refs)
        elif block.kind == "list":
            paragraph = document.add_paragraph(style="GOST List")
            paragraph.paragraph_format.left_indent = Cm(1.25 + min(block.level, 4) * 0.63)
            marker = "•" if block.marker in {"-", "+", "*"} else block.marker.rstrip(".)") + "."
            run = paragraph.add_run(marker + " ")
            _format_run(run, 14)
            add_inline(paragraph, block.text, source, bookmarks, figure_refs=figure_refs)
        elif block.kind == "code":
            paragraph = document.add_paragraph(style="GOST Code")
            run = paragraph.add_run(block.text)
            _format_run(run, 12)
        elif block.kind == "table":
            table_number += 1
            add_table(
                document, block.rows, source, bookmarks, table_number, current_heading, figure_refs
            )
        elif block.kind == "figure":
            figure = figures_by_id.get(block.target)
            if figure.identifier not in used_figures:
                figure_number += 1
                if figure_refs[figure.identifier] != figure_number:
                    raise RuntimeError(f"Нарушена последовательность рисунков для {figure.identifier}")
                add_figure(
                    document, figure, figure_number,
                    add_reference=figure.identifier not in referenced_ids,
                )
                used_figures.add(figure.identifier)
                figure_numbers[figure.identifier] = figure_number
        elif block.kind == "image":
            figure_number += 1
            _add_markdown_image(document, source, block, figure_number)

    return figure_number, table_number, bookmark_id


def _ensure_black(document: Document) -> None:
    paragraphs = list(document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs.extend(cell.paragraphs)
    for section in document.sections:
        paragraphs.extend(section.header.paragraphs)
        paragraphs.extend(section.footer.paragraphs)
    for paragraph in paragraphs:
        for run in paragraph.runs:
            _format_run(run)


def build_document(spec: DocumentSpec, output: Path, figures: Sequence[Figure]) -> None:
    missing = [source for source in spec.sources if not source.is_file()]
    if missing:
        raise FileNotFoundError("Не найдены источники: " + ", ".join(map(str, missing)))
    parsed = {source: parse_markdown(source) for source in spec.sources}
    bookmarks = _source_bookmarks(spec.sources)
    document = Document()
    _configure_document(document, spec.title)
    title = document.add_paragraph(spec.title, style="Title")
    for run in title.runs:
        _format_run(run, 14, bold=True)
    for metadata in (
        "Дата редакции: 11 октября 2026 года",
        "Статус: редактируемый комплект сопроводительных материалов проекта",
        "Содержание включает текущие и исторические документы; исходные даты и статусы сохранены.",
    ):
        paragraph = document.add_paragraph(style="GOST Cover Metadata")
        run = paragraph.add_run(metadata)
        _format_run(run, 14)
    _add_body_section(document)
    if spec.navigation:
        _add_navigation(document, spec, parsed, bookmarks)
    figure_number = 0
    table_number = 0
    bookmark_id = 1
    used_figures: set[str] = set()
    figure_numbers: dict[str, int] = {}
    for source_index, source in enumerate(spec.sources):
        paragraph_count = len(document.paragraphs)
        figure_number, table_number, bookmark_id = _blocks_for_source(
            document, source, parsed[source], bookmarks, figures, used_figures, figure_numbers,
            figure_number, table_number, bookmark_id
        )
        if len(document.paragraphs) == paragraph_count:
            raise ValueError(f"Источник не создал ни одного абзаца: {source}")
        if spec.navigation or source_index > 0:
            document.paragraphs[paragraph_count].paragraph_format.page_break_before = True
    unused_figures = [
        figure for figure in figures
        if figure.identifier not in used_figures and any(figure.matches(source) for source in spec.sources)
    ]
    if unused_figures:
        heading = document.add_paragraph("Приложение А. Иллюстрации интерфейса", style="Heading 1")
        heading.paragraph_format.page_break_before = True
        for run in heading.runs:
            _format_run(run, 14, bold=True)
        for figure in unused_figures:
            figure_number += 1
            add_figure(document, figure, figure_number)
            used_figures.add(figure.identifier)
            figure_numbers[figure.identifier] = figure_number
    _ensure_black(document)
    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(output)
    # Word может читать отдельную stylesWithEffects часть из исходного шаблона.
    # Синхронизируем её с фактическими чёрными стилями, включая новые GOST-стили.
    from zipfile import ZipFile
    temporary = output.with_suffix('.docx.tmp')
    with ZipFile(output) as existing, ZipFile(temporary, 'w') as rewritten:
        actual_styles = existing.read('word/styles.xml')
        for info in existing.infolist():
            data = actual_styles if info.filename == 'word/stylesWithEffects.xml' else existing.read(info.filename)
            rewritten.writestr(info, data)
    temporary.replace(output)


def build_all(
    output_dir: Path,
    manifest: Path,
    document_set: Path = DEFAULT_DOCUMENT_SET,
    only: Sequence[str] = (),
) -> tuple[Path, ...]:
    figures = load_figures(manifest)
    specs = document_specs(document_set)
    requested = set(only)
    if requested:
        available = {spec.key for spec in specs}
        unknown = requested - available
        if unknown:
            raise ValueError("Неизвестные документы: " + ", ".join(sorted(unknown)))
        specs = tuple(spec for spec in specs if spec.key in requested)
    outputs: list[Path] = []
    for spec in specs:
        output = output_dir / spec.filename
        build_document(spec, output, figures)
        outputs.append(output)
        print(f"{output}: источников {len(spec.sources)}")
    return tuple(outputs)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--document-set", type=Path, default=DEFAULT_DOCUMENT_SET)
    parser.add_argument(
        "--only", action="append", default=[],
        help="Собрать только выбранный документ; параметр можно повторять",
    )
    arguments = parser.parse_args(argv)
    build_all(arguments.out_dir, arguments.manifest, arguments.document_set, arguments.only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

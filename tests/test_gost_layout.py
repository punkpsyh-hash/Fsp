from pathlib import Path

from pypdf import PdfReader
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.platypus import KeepTogether, Paragraph, Spacer

from scripts.gost_layout import ROOT, GostContext, gost_document, markdown


def _diagram() -> Drawing:
    drawing = Drawing(400, 220)
    drawing.add(Rect(1, 1, 398, 218, strokeWidth=1, fillColor=None))
    drawing.add(String(20, 110, "DIAGRAM-BODY", fontSize=14))
    return drawing


def _paragraphs(flowable):
    if isinstance(flowable, Paragraph):
        yield flowable
    elif isinstance(flowable, KeepTogether):
        for child in flowable._content:
            yield from _paragraphs(child)


def test_markdown_parses_star_bullets_and_balances_short_source_tail(tmp_path: Path):
    source = tmp_path / "source.md"
    source.write_text(
        "# Проверка\n\n"
        "Вводный абзац.\n\n"
        "* Первый пункт продолжается\n"
        "  на следующей строке.\n"
        "* Завершающий пункт.\n",
        encoding="utf-8",
    )

    story = markdown(source, skip_first_h1=False)
    paragraphs = [paragraph for flowable in story for paragraph in _paragraphs(flowable)]
    bullets = [paragraph for paragraph in paragraphs if paragraph.style.name == "bullet"]

    assert [paragraph.getPlainText() for paragraph in bullets] == [
        "Первый пункт продолжается на следующей строке.",
        "Завершающий пункт.",
    ]
    assert all(not paragraph.getPlainText().startswith("*") for paragraph in paragraphs)
    assert isinstance(story[-1], KeepTogether)
    assert [child.style.name for child in story[-1]._content] == ["bullet", "bullet"]


def test_heading_and_short_reference_stay_with_figure_in_rendered_pdf(tmp_path: Path):
    source = tmp_path / "figure.md"
    source.write_text(
        "## 2. Функциональная и компонентная архитектура\n\n"
        "Материал приведён на [[figure:architecture]].\n\n"
        "<!-- figure:architecture -->\n",
        encoding="utf-8",
    )
    story = markdown(
        source,
        skip_first_h1=False,
        context=GostContext(manifest_path=tmp_path / "missing.json"),
        diagrams={"architecture": (_diagram, "Компоненты решения")},
    )

    assert len(story) == 1 and isinstance(story[0], KeepTogether)
    heading, reference, generated_reference, drawing, caption = story[0]._content
    assert isinstance(heading, Paragraph) and heading.style.keepWithNext
    assert isinstance(reference, Paragraph) and reference.style.name == "reference"
    assert reference.style.keepWithNext
    assert isinstance(generated_reference, Paragraph) and generated_reference.style.name == "reference"
    assert not any(isinstance(child, KeepTogether) for child in story[0]._content)

    output = tmp_path / "figure.pdf"
    document = gost_document(output, title="Проверка", author="tests")
    document.build([Spacer(1, 500), *story])
    pages = [page.extract_text() for page in PdfReader(output).pages]

    heading_page = next(index for index, text in enumerate(pages) if "Функциональная" in text)
    caption_page = next(index for index, text in enumerate(pages) if "Компоненты решения" in text)
    assert heading_page == caption_page


def test_real_docs34_legacy_diagram_groups_heading_without_nested_keep_together():
    story = markdown(
        ROOT / "docs/34-documentation.md",
        skip_first_h1=False,
        diagrams={"diagram_components": (_diagram, "Компоненты решения")},
    )
    group = next(
        flowable
        for flowable in story
        if isinstance(flowable, KeepTogether)
        and any(
            isinstance(child, Paragraph) and "Функциональная и компонентная" in child.getPlainText()
            for child in flowable._content
        )
    )

    assert group._content[0].style.name == "h2"
    assert any(
        isinstance(child, Paragraph) and "Компоненты решения" in child.getPlainText()
        for child in group._content
    )
    assert not any(isinstance(child, KeepTogether) for child in group._content)


def test_source_end_balance_includes_immediate_keep_with_next_heading(tmp_path: Path):
    source = tmp_path / "ending.md"
    source.write_text(
        "## 13. Заключение\n\n"
        "Первый короткий абзац заключения.\n\n"
        "Второй короткий абзац заключения.\n",
        encoding="utf-8",
    )

    story = markdown(source, skip_first_h1=False)

    assert len(story) == 1 and isinstance(story[0], KeepTogether)
    assert [child.style.name for child in story[0]._content] == ["h2", "body", "body"]

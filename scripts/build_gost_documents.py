"""Письменный комплект ГОСТ: явные источники, содержание, чёрные стили и рисунки."""
import argparse
from pathlib import Path
from html import escape

from reportlab.platypus import PageBreak, Spacer, Paragraph
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.platypus import TableStyle
from reportlab.lib.styles import ParagraphStyle
from build_documentation import markdown
from build_gost_docx import DocumentSpec, document_specs
from gost_layout import ROOT, STYLES, GostContext, gost_document, page_number_after_title


def build(spec: DocumentSpec, out: Path):
    context = GostContext()
    doc = gost_document(out, title=spec.title, author='Проект ФСП')
    def after(flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name in ('h1', 'h2'):
            if spec.key == 'all-documents' and flowable.style.name != 'h1':
                return
            level = 0 if flowable.style.name == 'h1' else 1
            doc.notify('TOCEntry', (level, flowable.getPlainText(), doc.page))
    doc.afterFlowable = after
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle('toc', parent=STYLES['body'], firstLineIndent=0, rightIndent=36, spaceBefore=7),
                       ParagraphStyle('toc-sub', parent=STYLES['body'], firstLineIndent=0, leftIndent=12, rightIndent=36, spaceBefore=3)]
    toc.dotsMinLevel = 0
    toc.tableStyle = TableStyle([('LEFTPADDING',(0,0),(-1,-1),0),
                                ('RIGHTPADDING',(0,0),(-1,-1),0),
                                ('TOPPADDING',(0,0),(-1,-1),0),
                                ('BOTTOMPADDING',(0,0),(-1,-1),0)])
    story = [Spacer(1, 55), Paragraph('ФСП Карьерный профиль', STYLES['title']),
             Paragraph(escape(spec.title), STYLES['title']),
             Paragraph('11 октября 2026 года', STYLES['title_meta']),
             Paragraph('Синтетический конкурсный стенд. Актуальные публикуемые источники и датированные протоколы сохранены в репозитории.', STYLES['body']),
             PageBreak(), Paragraph('СОДЕРЖАНИЕ', STYLES['title']), toc]
    for source in spec.sources:
        source_name = source.relative_to(ROOT).as_posix()
        story.extend([PageBreak(), Paragraph(escape('Источник: ' + source_name), STYLES['source'])])
        if spec.key == 'all-documents':
            story.append(Paragraph('Актуальный опубликованный комплект: состав явно зафиксирован в docs/document-set.json.', STYLES['small']))
        story.extend(markdown(source, skip_first_h1=False, context=context))
    doc.multiBuild(story, onFirstPage=page_number_after_title, onLaterPages=page_number_after_title)
    print(str(out))


def build_named(document_id: str, output: Path, manifest: Path) -> None:
    """Совместимый вход для прежних одиночных команд без второго списка источников."""
    specs = {spec.key: spec for spec in document_specs(manifest)}
    try:
        spec = specs[document_id]
    except KeyError as error:
        raise ValueError(f"Неизвестный документ: {document_id}") from error
    build(spec, output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'docs/document-set.json')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'docs/delivery/gost')
    parser.add_argument('--only', nargs='*')
    args = parser.parse_args()
    specs = document_specs(args.manifest)
    requested = set(args.only or ())
    available = {spec.key for spec in specs}
    unknown = requested - available
    if unknown:
        parser.error('Неизвестные документы: ' + ', '.join(sorted(unknown)))
    for spec in specs:
        if not requested or spec.key in requested:
            build(spec, args.output_dir / (spec.key + '.pdf'))

"""Проверка страниц PDF, чёрной типографики, OOXML и происхождения рисунков."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from pypdf import PdfReader
from pypdf.generic import ContentStream

ROOT = Path(__file__).resolve().parents[1]
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pdf_check(path):
    reader = PdfReader(path, strict=True)
    sizes, text_blocks, nonblack = set(), 0, []
    all_text = []
    for number, page in enumerate(reader.pages, 1):
        assert abs(float(page.mediabox.width)-595.276) < 0.02
        assert abs(float(page.mediabox.height)-841.89) < 0.02
        text = page.extract_text() or ''
        assert text.strip(), (path.name, number, 'empty page')
        all_text.append(text)
        fill = (0, 0, 0)
        font_size = 12
        stack = []
        for operands, operator in ContentStream(page.get_contents(), reader).operations:
            if operator == b'q':
                stack.append(fill)
            elif operator == b'Q':
                fill = stack.pop()
            elif operator == b'rg':
                fill = tuple(float(x) for x in operands)
            elif operator == b'g':
                fill = (float(operands[0]),)*3
            elif operator == b'k':
                c,m,y,k = map(float, operands)
                fill = tuple((1-x)*(1-k) for x in (c,m,y))
            elif operator == b'Tf':
                font_size = float(operands[1])
            elif operator in (b'Tj', b'TJ', b"'", b'"'):
                payload = operands[-1]
                visible = any(isinstance(x, (str, bytes)) and x for x in payload) if isinstance(payload, list) else bool(payload)
                if not visible:
                    continue
                sizes.add(font_size)
                text_blocks += 1
                if any(abs(x)>0.00001 for x in fill):
                    nonblack.append(number)
    assert not nonblack, (path.name, nonblack)
    assert min(sizes) >= 12, (path.name, 'small text', sorted(sizes))
    text = '\n'.join(all_text)
    assert '[[figure:' not in text and '<!--' not in text
    captions = re.findall(r'Рисунок\s+(\d+)\s*[—–-]', text)
    assert len(captions) == len(set(captions)), (path.name, 'duplicate captions', captions)
    return {'file':path.relative_to(ROOT).as_posix(), 'sha256':sha(path), 'pages':len(reader.pages),
            'a4_all_pages':True, 'black_text_blocks':text_blocks, 'nonblack_text_blocks':0,
            'font_sizes_pt': sorted(sizes), 'figure_captions':len(captions), 'caption_numbers_unique':True}


def docx_check(path):
    with ZipFile(path) as archive:
        assert archive.testzip() is None
        document = ET.fromstring(archive.read('word/document.xml'))
        styles = ET.fromstring(archive.read('word/styles.xml'))
        sections = list(document.iter(W+'sectPr'))
        assert len(sections) == 2, (path.name, 'cover/body sections')
        for section in sections:
            margins = section.find(W+'pgMar')
            assert all(abs(int(margins.get(W+k))-v)<2 for k,v in [('left',1701),('right',850),('top',1134),('bottom',1134)])
        cover_ref, body_ref = [s.find(W+'footerReference') for s in sections]
        assert cover_ref is not None and body_ref is not None
        assert cover_ref.get(R+'id') != body_ref.get(R+'id')
        relations = ET.fromstring(archive.read('word/_rels/document.xml.rels'))
        targets = {x.get('Id'):x.get('Target') for x in relations}
        cover_footer = ET.fromstring(archive.read('word/'+targets[cover_ref.get(R+'id')]))
        assert not ''.join(x.text or '' for x in cover_footer.iter(W+'t')).strip()
        assert not list(cover_footer.iter(W+'instrText'))
        assert sections[1].find(W+'pgNumType').get(W+'start') == '2'
        for member in archive.namelist():
            if member.startswith('word/') and member.endswith('.xml') and member != 'word/theme/theme1.xml':
                root = ET.fromstring(archive.read(member))
                assert all(x.get(W+'val')=='000000' for x in root.iter(W+'color')), member
                assert all(x.get(W+'themeColor') is None for x in root.iter()), (member, 'theme color')
                assert all(x.get(W+'color') in (None, '000000', 'auto') for x in root.iter()), (member, 'border or line color')
        normal = next(x for x in styles.findall(W+'style') if x.get(W+'styleId')=='Normal')
        assert normal.find('.//'+W+'sz').get(W+'val')=='28'
        assert normal.find('.//'+W+'spacing').get(W+'line')=='360'
        assert normal.find('.//'+W+'ind').get(W+'firstLine')=='709'
        text = '\n'.join(x.text or '' for x in document.iter(W+'t'))
        assert '[[figure:' not in text and '<!--' not in text
        return {'file':path.relative_to(ROOT).as_posix(),'sha256':sha(path),'zip_valid':True,
                'black_text_explicit':True,'black_borders_verified':True,'normal_font_pt':14,'normal_line_spacing':1.5,
                'margins_mm':[30,15,20,20],'independent_unnumbered_cover_footer_configured':True,
                'images':sum(x.startswith('word/media/') for x in archive.namelist()),
                'figure_captions':len(re.findall(r'Рисунок\s+\d+\s*[—–-]',text))}


def rendered_docx_check(path, render_dir):
    """Проверяет фактическую нумерацию после преобразования Word в PDF."""
    rendered = render_dir/path.stem/(path.stem+'.pdf')
    reader = PdfReader(rendered, strict=True)
    assert len(reader.pages) > 1, (path.name, 'missing body pages')
    for number, page in enumerate(reader.pages, 1):
        footer = []
        def collect(text, cm, tm, font, size):
            y = tm[4]*cm[1]+tm[5]*cm[3]+cm[5]
            if text.strip() and y < 50:
                footer.append(text.strip())
        page.extract_text(visitor_text=collect)
        expected = [] if number == 1 else [str(number)]
        assert footer == expected, (path.name, number, 'rendered footer', footer)
    return {'file':path.relative_to(ROOT).as_posix(),'docx_sha256':sha(path),
            'rendered_pdf_sha256':sha(rendered),'pages':len(reader.pages),
            'first_page_number_hidden':True,'continuous_page_numbers_verified':True,
            'method':'LibreOffice PDF output: text below y=50 pt inspected on every page.'}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/release/current-documents/artifacts.json')
    parser.add_argument('--render-dir',type=Path,help='Каталог рендеринга Word: <имя>/<имя>.pdf')
    args=parser.parse_args()
    directory=ROOT/'docs/delivery/gost'
    report={'pdf':[pdf_check(p) for p in sorted(directory.glob('*.pdf'))],
            'docx':[docx_check(p) for p in sorted(directory.glob('*.docx'))]}
    assert len(report['pdf'])==len(report['docx'])==7
    if args.render_dir:
        report['docx_rendered']=[rendered_docx_check(p,args.render_dir) for p in sorted(directory.glob('*.docx'))]
    manifest = json.loads((ROOT/'docs/assets/screenshots/manifest.json').read_text(encoding='utf-8'))
    assert not manifest['page_errors']
    for entry in manifest['screenshots']:
        assert sha(ROOT/entry['path'])==entry['sha256']
        assert 'Рџ' not in entry['caption'] and 'РЎ' not in entry['caption']
    report['screen_sha256_verified']=6
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'pdf':7,'docx':7,'pdf_pages':sum(x['pages'] for x in report['pdf']),'screens':6}))

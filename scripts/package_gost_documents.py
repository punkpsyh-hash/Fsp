"""Архив письменных материалов: явный состав без данных стенда и секретов."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from build_gost_docx import DEFAULT_DOCUMENT_SET, document_specs

ROOT = Path(__file__).resolve().parents[1]


def package(output: Path, report_path: Path, document_set_path: Path = DEFAULT_DOCUMENT_SET) -> dict:
    specs = document_specs(document_set_path)
    paths = {
        'docs/document-set.json', 'docs/delivery/gost/README.md',
        'docs/assets/screenshots/manifest.json', 'docs/delivery/fsp-lct-2026.pptx',
        'docs/third-party-components.json',
    }
    for document in specs:
        paths.update(source.relative_to(ROOT).as_posix() for source in document.sources)
        for extension in ('pdf', 'docx'):
            paths.add(f"docs/delivery/gost/{document.key}.{extension}")
    for directory in ('docs/assets/screenshots', 'docs/assets/diagrams', 'resources/fonts'):
        paths.update(path.relative_to(ROOT).as_posix() for path in (ROOT / directory).iterdir()
                     if path.is_file() and path.suffix.lower() in ('.png', '.svg', '.ttf', '.txt', '.md', '.json'))
    paths.update(path.relative_to(ROOT).as_posix() for path in (ROOT / 'resources/licenses/third-party').rglob('*') if path.is_file())
    paths.add('resources/DejaVu-LICENSE.txt')
    source_count = len(next(item for item in specs if item.key == 'all-documents').sources)
    payloads = {name: (ROOT / name).read_bytes() for name in sorted(paths)}
    payloads['docs/document-set.json'] = document_set_path.read_bytes()
    payloads['README.txt'] = (
        'ФСП — Карьерный профиль. Комплект документов от 11 октября 2026 года.\n\n'
        '7 документов в PDF и редактируемом Word: docs/delivery/gost/.\n'
        'Инструкция запуска: self-deployment-guide.docx и self-deployment-guide.pdf.\n'
        f'Актуальный комплект содержит {source_count} явно опубликованных исходных документов.\n'
        'Конкурсная презентация: docs/delivery/fsp-lct-2026.pptx.\n'
        'Снимки работающего синтетического стенда и схемы: docs/assets/.\n'
        'Оформление и его границы: docs/55-document-formatting.md.\n'
        'Лицензии компонентов: resources/licenses/third-party/; реестр: docs/third-party-components.json.\n'
        'SHA-256 каждого вложения: MANIFEST.json.\n\n'
        'Для запуска приложения клонируйте репозиторий по инструкции. Этот архив\n'
        'содержит документы, иллюстрации и шрифты; исходный код приложения, модель,\n'
        'токены и базы пользователей сюда не входят.\n'
    ).encode('utf-8')
    manifest = {
        'date': '2026-10-11', 'pdf_documents': 7, 'word_documents': 7,
        'files': [{'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                  for name, data in sorted(payloads.items())],
    }
    payloads['MANIFEST.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'w', compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(payloads.items()):
            info = ZipInfo(name, date_time=(2026, 10, 11, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(payloads)
        for entry in manifest['files']:
            assert hashlib.sha256(archive.read(entry['path'])).hexdigest() == entry['sha256']
    report = {'archive': output.relative_to(ROOT).as_posix(), 'bytes': output.stat().st_size,
              'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
              'entries': len(payloads), 'zip_valid': True, 'all_entry_sha256_verified': True}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/delivery/fsp-documents-gost.zip')
    parser.add_argument('--report', type=Path, default=ROOT / 'docs/release/current-documents/package.json')
    parser.add_argument('--manifest', type=Path, default=DEFAULT_DOCUMENT_SET)
    args = parser.parse_args()
    print(json.dumps(package(args.output.resolve(), args.report.resolve(), args.manifest.resolve()), ensure_ascii=False))

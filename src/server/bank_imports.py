"""Импорт только данных: без извлечения ZIP на диск и без выполнения кода."""
import csv
from hashlib import sha256
from io import BytesIO, StringIO
from itertools import islice
import json
import subprocess
import sys
from pathlib import PurePosixPath
import stat
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree
from pydantic import ValidationError
from .bank_schemas import BankDocument

MAX_UPLOAD = 2 * 1024 * 1024
MAX_EXPANDED = 4 * 1024 * 1024
MAX_FILES = 50


def bounded_json(raw):
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Повторяющийся ключ JSON')
            result[key] = value
        return result
    obj = json.loads(raw, object_pairs_hook=no_duplicates,
                     parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Неконечное число JSON')))
    def visit(value, depth=0):
        if depth > 16: raise ValueError('Глубина JSON превышает 16 уровней')
        if isinstance(value, dict):
            for item in value.values(): visit(item, depth+1)
        elif isinstance(value, list):
            if len(value) > 200: raise ValueError('Слишком длинный массив JSON')
            for item in value: visit(item, depth+1)
    visit(obj)
    return obj


def zip_files(raw):
    result = {}
    with ZipFile(BytesIO(raw)) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES: raise ValueError('ZIP содержит больше 50 файлов')
        if sum(info.file_size for info in infos) > MAX_EXPANDED:
            raise ValueError('ZIP после распаковки превышает 4 МБ')
        for info in infos:
            name = info.filename
            path = PurePosixPath(name)
            if ('\\' in name or '\x00' in name or path.is_absolute() or '..' in path.parts
                    or len(path.parts) > 5 or ':' in name or name in result
                    or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1):
                raise ValueError('ZIP содержит небезопасный путь, ссылку, дубликат или шифрование')
            if info.is_dir(): continue
            if info.file_size > MAX_UPLOAD: raise ValueError('Файл ZIP превышает 2 МБ')
            if info.compress_size and info.file_size / info.compress_size > 100:
                raise ValueError('Недопустимая степень сжатия ZIP')
            content = archive.read(info)
            if len(content) != info.file_size: raise ValueError('Повреждённый файл ZIP')
            result[name] = content
    return result


def parse_csv(raw, digest, column_mapping=None):
    text = raw.decode('utf-8-sig')
    reader = csv.DictReader(StringIO(text))
    allowed = {'id', 'type', 'title', 'prompt', 'skills', 'options', 'answer_key', 'numeric_answer',
               'absolute_tolerance', 'relative_tolerance', 'unit', 'weight', 'partial_credit',
               'bank_title', 'external_id', 'specialization', 'grade', 'csv_escape'}
    required = {'id', 'type', 'title', 'prompt', 'skills'}
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError('CSV: отсутствуют или повторяются названия колонок')
    mapping = column_mapping or {}
    if not isinstance(mapping, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in mapping.items()):
        raise ValueError('CSV: сопоставление колонок должно быть объектом строк')
    if not set(mapping) <= set(reader.fieldnames) or any(value and value not in allowed for value in mapping.values()):
        raise ValueError('CSV: сопоставление содержит неизвестные входные или целевые колонки')
    renamed = [mapping.get(name, name) for name in reader.fieldnames]
    active = [name for name in renamed if name]
    if len(set(active)) != len(active): raise ValueError('CSV: несколько колонок сопоставлены одному полю')
    if not required <= set(active) or not set(active) <= allowed:
        raise ValueError('CSV: обязательные колонки id,type,title,prompt,skills; неизвестные колонки запрещены')
    original_rows = list(islice(reader, 101))
    if any(None in row or any(value is None for value in row.values()) for row in original_rows):
        raise ValueError('CSV: неверное число колонок')
    rows = [{mapping.get(key, key): value for key, value in row.items() if mapping.get(key, key)} for row in original_rows]
    if not rows or len(rows) > 100: raise ValueError('CSV должен содержать от 1 до 100 заданий')
    if any(row.get('csv_escape', '') not in {'', 'apostrophe-v1'} for row in rows):
        raise ValueError('CSV: неизвестная версия экранирования')
    if len({row.get('csv_escape', '') for row in rows}) != 1:
        raise ValueError('CSV: csv_escape должен совпадать во всех строках')
    if rows[0].get('csv_escape') == 'apostrophe-v1':
        for row in rows:
            for key, value in row.items():
                if value.startswith("'") and value.lstrip("'").lstrip().startswith(('=', '+', '-', '@', '\t', '\r')):
                    row[key] = value[1:]
    tasks = []
    for line, row in enumerate(rows, 2):
        if None in row or any(value is None for value in row.values()): raise ValueError(f'CSV строка {line}: неверное число колонок')
        if row['type'] not in {'single_choice', 'multiple_choice', 'numeric'}:
            raise ValueError(f'CSV строка {line}: вложенные задания импортируются через JSON')
        task = {key: row[key] for key in ['id', 'type', 'title', 'prompt']}
        task['skills'] = [v.strip() for v in row['skills'].split(';') if v.strip()]
        for key in ['options', 'answer_key']:
            if row.get(key): task[key] = bounded_json(row[key])
        for key in ['numeric_answer', 'absolute_tolerance', 'relative_tolerance', 'weight']:
            if row.get(key): task[key] = float(row[key].replace(',', '.'))
        if row.get('unit'): task['unit'] = row['unit']
        if row.get('partial_credit'):
            if row['partial_credit'].lower() not in {'true', 'false'}: raise ValueError(f'CSV строка {line}: partial_credit true/false')
            task['partial_credit'] = row['partial_credit'].lower() == 'true'
        tasks.append(task)
    first = rows[0]
    for key in ['bank_title', 'external_id', 'specialization', 'grade']:
        if any(row.get(key) and row.get(key) != first.get(key) for row in rows[1:]):
            raise ValueError('CSV: метаданные набора должны совпадать во всех строках')
    return {'schema_version': 'fsp-bank-v1', 'external_id': first.get('external_id') or 'csv-'+digest[:16],
            'title': first.get('bank_title') or 'Импорт CSV', 'specialization': first.get('specialization') or 'backend',
            'grade': first.get('grade') or 'junior', 'tasks': tasks}


def extracted_document(raw, suffix, digest):
    if suffix == '.pdf':
        if not raw.startswith(b'%PDF-'): raise ValueError('Неверный заголовок PDF')
        # Декомпрессия PDF имеет отдельные CPU/память/timeout, не блокирует API навсегда.
        program = '''import json, logging, resource, sys
from io import BytesIO
resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
resource.setrlimit(resource.RLIMIT_AS, (384*1024*1024, 384*1024*1024))
from pypdf import PdfReader
logging.getLogger('pypdf').setLevel(logging.CRITICAL)
reader = PdfReader(BytesIO(sys.stdin.buffer.read(2097153)), strict=True)
if reader.is_encrypted or len(reader.pages)>30: raise ValueError('PDF format')
text = ''
for page in reader.pages:
    text += '\\n' + (page.extract_text() or '')[:12000]
    if len(text)>=12000: break
print(json.dumps(text[:12000], ensure_ascii=False))
'''
        try:
            result = subprocess.run([sys.executable, '-c', program], input=raw, capture_output=True,
                                    timeout=6, env={'LANG': 'C.UTF-8'}, check=False)
            if result.returncode: raise ValueError('PDF должен быть без шифрования, до 30 страниц и укладываться в лимиты разбора')
            text = json.loads(result.stdout)
        except subprocess.TimeoutExpired: raise ValueError('PDF превысил время безопасного разбора')
    else:
        files = zip_files(raw)
        xml = files.get('word/document.xml')
        if not xml: raise ValueError('DOCX: отсутствует word/document.xml')
        if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper(): raise ValueError('XML entities запрещены')
        root = ElementTree.fromstring(xml)
        text = '\n'.join(element.text or '' for element in root.iter() if element.tag.endswith('}t'))
    text = text.strip()
    if not text: raise ValueError('Не найден текст: сканирование/OCR не поддерживается')
    # Импортированный текст отображается как plain text; raw HTML не разрешается.
    text = text.replace('<', '‹').replace('>', '›')[:12000]
    return {'schema_version': 'fsp-bank-v1', 'external_id': 'document-'+digest[:16],
            'title': 'Черновик из документа', 'tasks': [{'id': 'extracted-task', 'type': 'open_response',
                      'title': 'Условие из документа', 'prompt': text, 'skills': [], 'rubric': ''}]}


def parse_import(raw, filename, column_mapping=None):
    digest = sha256(raw).hexdigest()
    warnings = []
    try:
        if not raw: raise ValueError('Файл пуст')
        if len(raw) > MAX_UPLOAD: raise ValueError('Файл превышает 2 МБ')
        suffix = PurePosixPath(filename.lower()).suffix
        if column_mapping and suffix != '.csv': raise ValueError('Сопоставление колонок доступно только для CSV')
        if suffix == '.json': obj = bounded_json(raw.decode('utf-8-sig'))
        elif suffix == '.csv': obj = parse_csv(raw, digest, column_mapping)
        elif suffix == '.zip':
            files = zip_files(raw)
            if 'manifest.json' not in files: raise ValueError('ZIP: необходим manifest.json')
            if any(PurePosixPath(name).suffix not in {'.json', '.py', '.js', '.sql', '.txt', '.csv'} for name in files):
                raise ValueError('ZIP: разрешены JSON, PY, JS, SQL, TXT и CSV')
            obj = bounded_json(files['manifest.json'].decode('utf-8-sig'))
            for task in obj.get('tasks', []):
                file = task.pop('starter_file', None)
                if file is not None:
                    if file not in files or PurePosixPath(file).suffix not in {'.py', '.js', '.sql', '.txt'}:
                        raise ValueError('starter_file отсутствует или имеет запрещённый формат')
                    task['starter_code'] = files[file].decode('utf-8')
        elif suffix in {'.pdf', '.docx'}:
            obj = extracted_document(raw, suffix, digest)
            warnings = ['Из документа извлечён только текст. Автор обязан разметить задания, навыки, ключи и рубрику перед публикацией.']
        else: raise ValueError('Допустимые форматы: JSON, CSV, ZIP, текстовые PDF/DOCX')
        document = BankDocument.model_validate(obj).model_dump(mode='json')
        return document, [], warnings
    except ValidationError as error:
        return None, [{'path': '.'.join(map(str, item['loc'])), 'message': item['msg']} for item in error.errors()], warnings
    except (ValueError, TypeError, KeyError, UnicodeError, BadZipFile, ElementTree.ParseError, RecursionError) as error:
        return None, [{'path': 'file', 'message': str(error)[:300]}], warnings
    except Exception:
        # Парсер PDF может возвращать формат-зависимые исключения. Не выдаём внутренние пути.
        return None, [{'path': 'file', 'message': 'Не удалось прочитать документ указанного формата'}], warnings


def csv_export(document):
    output = StringIO()
    fields = ['id', 'type', 'title', 'prompt', 'skills', 'options', 'answer_key', 'numeric_answer',
              'absolute_tolerance', 'relative_tolerance', 'unit', 'weight', 'partial_credit',
              'bank_title', 'external_id', 'specialization', 'grade', 'csv_escape']
    writer = csv.DictWriter(output, fields)
    writer.writeheader()
    for task in document['tasks']:
        if task['type'] not in {'single_choice', 'multiple_choice', 'numeric'}:
            raise ValueError('Этот набор содержит вложенные типы: используйте JSON export')
        row = {key: task.get(key, '') for key in fields}
        row.update(bank_title=document['title'], external_id=document['external_id'],
                   specialization=document['specialization'], grade=document['grade'],
                   skills=';'.join(task['skills']), options=json.dumps(task['options'], ensure_ascii=False),
                   answer_key=json.dumps(task['answer_key']), partial_credit=str(task['partial_credit']).lower(), csv_escape='apostrophe-v1')
        for key, value in row.items():
            if isinstance(value, str) and value.lstrip("'").lstrip().startswith(('=', '+', '-', '@', '\t', '\r')):
                row[key] = "'" + value
        writer.writerow(row)
    return '\ufeff'+output.getvalue()

"""Авторский синтетический пример; ключи остаются на сервере."""
import json
from pathlib import Path
from .bank_schemas import BankDocument
from .bank_models import TaskBank, BankVersion
from .models import User, now
from .banks import digest


def example_document():
    return BankDocument.model_validate({
        'schema_version': 'fsp-bank-v1', 'external_id': 'synthetic-all-types-v1',
        'title': 'Практика: пять типов и три языка', 'scope': 'employer',
        'specialization': 'backend', 'grade': 'junior', 'time_limit_minutes': 90,
        'tasks': [
            {'id': 'http-choice', 'type': 'single_choice', 'title': 'Успешный HTTP-запрос',
             'prompt': 'Какой статус обозначает успешно обработанный GET-запрос?', 'skills': ['http'],
             'options': [{'id': 'ok', 'text': '200'}, {'id': 'absent', 'text': '404'}, {'id': 'error', 'text': '500'}], 'answer_key': ['ok']},
            {'id': 'sql-choice', 'type': 'multiple_choice', 'title': 'Выбор команд SQL',
             'prompt': 'Выберите команды SQL для чтения и изменения строк.', 'skills': ['sql'],
             'options': [{'id': 'select', 'text': 'SELECT'}, {'id': 'update', 'text': 'UPDATE'}, {'id': 'print', 'text': 'PRINT'}],
             'answer_key': ['select', 'update'], 'partial_credit': True},
            {'id': 'time-number', 'type': 'numeric', 'title': 'Преобразование времени',
             'prompt': 'Сколько секунд в двух минутах?', 'skills': ['testing'], 'numeric_answer': 120, 'unit': 'с', 'absolute_tolerance': 0},
            {'id': 'retry-open', 'type': 'open_response', 'title': 'Повторный запрос',
             'prompt': 'Опишите способ защиты API от повторного создания одного приглашения.', 'skills': ['http'],
             'rubric': '0: нет решения. 50: упомянут уникальный ключ. 100: ключ привязан к автору, параметры сверяются, результат повтора сохраняется.', 'answer_limit': 4000},
            {'id': 'sum-python', 'type': 'code', 'title': 'Сумма в Python', 'skills': ['python'], 'language': 'python',
             'prompt': 'В stdin поступает JSON-массив целых чисел. Напечатайте их сумму и перевод строки. Пустой массив даёт 0.',
             'starter_code': 'import json, sys\nvalues = json.loads(sys.stdin.read())\n# Напечатайте сумму\n',
             'examples': [{'input': '[1, 2, 3]', 'output': '6\n'}],
             'hidden_tests': [{'input': '[]', 'output': '0\n'}, {'input': '[-4, 7, 11]', 'output': '14\n'}]},
            {'id': 'sum-js', 'type': 'code', 'title': 'Сумма в JavaScript', 'skills': ['javascript'], 'language': 'javascript',
             'prompt': 'В stdin поступает JSON-массив целых чисел. Напечатайте сумму. Пустой массив даёт 0.',
             'starter_code': "const fs = require('node:fs');\nconst values = JSON.parse(fs.readFileSync(0, 'utf8'));\n// Напечатайте сумму\n",
             'examples': [{'input': '[1, 2, 3]', 'output': '6\n'}],
             'hidden_tests': [{'input': '[]', 'output': '0\n'}, {'input': '[-4, 7, 11]', 'output': '14\n'}]},
            {'id': 'count-sql', 'type': 'code', 'title': 'Сумма в SQL', 'skills': ['sql'], 'language': 'sql',
             'prompt': 'SQLite: таблица items(value INTEGER). Одним SELECT верните сумму в одной строке. Для пустой таблицы верните 0. Изменение данных запрещено.',
             'starter_code': '-- SELECT ... FROM items;\n',
             'examples': [{'setup': 'CREATE TABLE items(value INTEGER); INSERT INTO items VALUES (1),(2),(3);', 'output': '[[6]]'}],
             'hidden_tests': [{'setup': 'CREATE TABLE items(value INTEGER);', 'output': '[[0]]'},
                              {'setup': 'CREATE TABLE items(value INTEGER); INSERT INTO items VALUES (-4),(7),(11);', 'output': '[[14]]'}]},
        ]}).model_dump(mode='json')


def seed_banks(factory):
    """Добавляет авторские наборы один раз; существующие версии/ответы не заменяет."""
    with factory() as db:
        if not db.get(User, 'demo-employer-x'):
            return
        examples = [('demo-practice-all-types', example_document)]
        def contest_document():
            path = Path(__file__).resolve().parents[2] / 'requirements/examples/bank-contest.json'
            return BankDocument.model_validate(json.loads(path.read_text())).model_dump(mode='json')
        examples.append(('demo-practice-contest', contest_document))
        for bank_id, load in examples:
            if db.get(TaskBank, bank_id):
                continue
            document = load()
            bank = TaskBank(id=bank_id, owner_id='demo-employer-x',
                            external_id=document['external_id'], title=document['title'], scope='platform')
            db.add(bank); db.flush()
            payload = {key: document[key] for key in ['title', 'specialization', 'grade', 'time_limit_minutes', 'tasks']}
            db.add(BankVersion(id=bank_id+'-v1', bank_id=bank.id, number=1, revision=2,
                               state='published', document=payload, content_hash=digest(payload), published_at=now()))
        db.commit()

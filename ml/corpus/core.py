"""Общие функции корпуса обучения: сборка заданий с вычисленной истиной и проверка схемой продукта.

Корпус синтетический и авторский: ключ каждого вычисляемого примера получен
выполнением кода (sqlite3, Python, обход графа), а не словами модели. Тексты
курируемых утверждений написаны автором и просмотрены вручную.
"""
import json
import random
import re

from src.server import bank_generation as bg
from src.server import llm

KINDS = ('single_choice', 'multiple_choice', 'numeric', 'open_response')

INTROS = (
    'Создайте одно проверяемое задание', 'Подготовьте одно задание', 'Нужно одно проверяемое задание',
    'Составьте одно задание', 'Сделайте одно проверяемое задание', 'Предложите одно задание',
)
KIND_WORDS = {
    'single_choice': ('с одним верным вариантом', 'с выбором одного ответа', ''),
    'multiple_choice': ('с несколькими верными вариантами', 'с выбором нескольких ответов', ''),
    'numeric': ('с числовым ответом', 'с ответом в виде числа', ''),
    'open_response': ('с развёрнутым ответом', 'с открытым ответом и рубрикой', ''),
}


def intro(rng, kind):
    word = rng.choice(KIND_WORDS[kind])
    return rng.choice(INTROS) + (' ' + word if word else '')


def make_brief(rng, kind, scenario, topic, restriction=''):
    """Бриф автора: сценарий с данными, затем просьба и ограничения; форма как в реальных запросах."""
    parts = [scenario.strip(), f'{intro(rng, kind)} {about(topic)}.']
    if restriction:
        parts.append(restriction.strip())
    sep = '\n' if parts[0].rstrip().endswith('```') else ' '
    return sep.join(parts)


def about(topic):
    """«о» или «об» перед темой в предложном падеже."""
    return ('об ' if topic[:1].lower() in 'аоуиэ' else 'о ') + topic


def topic_brief(rng, kind, spec, grade, topic):
    """Краткий бриф без исходных данных: автор называет только тему и уровень."""
    who = {'backend': 'backend-разработчика', 'frontend': 'frontend-разработчика', 'qa': 'тестировщика (QA)'}[spec]
    first = intro(rng, kind)
    return rng.choice([
        f'{first} {about(topic)}. Специалист: {grade} {who}.',
        f'Нужно задание для {who}, уровень {grade}: вопрос {about(topic)}.',
        f'{first} {about(topic)}. Уровень: {grade}.',
        f'{first} для {who} уровня {grade}: вопрос {about(topic)}.',
    ])


def shuffled_options(rng, correct, wrong, many=False):
    """Вернуть options и answer_key; ключ вычислен после перемешивания."""
    items = [(text, True) for text in correct] + [(text, False) for text in wrong]
    rng.shuffle(items)
    ids = 'abcdef'[:len(items)]
    options = [{'id': ids[i], 'text': text} for i, (text, _) in enumerate(items)]
    key = [ids[i] for i, (_, ok) in enumerate(items) if ok]
    return options, key


def plural(n, one, few, many):
    """Русское склонение: 1 строка, 2 строки, 5 строк."""
    n = abs(int(n))
    if n % 100 in range(11, 15):
        return f'{n} {many}'
    return f'{n} ' + (one if n % 10 == 1 else few if n % 10 in (2, 3, 4) else many)


def fmt_num(value):
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return ('%.2f' % value).rstrip('0').rstrip('.')
    return str(value)


def single(rng, title, prompt, correct, wrong, skills):
    options, key = shuffled_options(rng, [correct], wrong)
    return {'id': 'suggestion', 'type': 'single_choice', 'title': title, 'prompt': prompt,
            'skills': skills, 'options': options, 'answer_key': key}


def multiple(rng, title, prompt, correct, wrong, skills):
    options, key = shuffled_options(rng, correct, wrong)
    return {'id': 'suggestion', 'type': 'multiple_choice', 'title': title, 'prompt': prompt,
            'skills': skills, 'options': options, 'answer_key': key}


def numeric(title, prompt, value, unit, skills):
    if isinstance(value, float) and value == int(value):
        value = int(value)
    return {'id': 'suggestion', 'type': 'numeric', 'title': title, 'prompt': prompt,
            'skills': skills, 'numeric_answer': value, 'unit': unit}


def open_task(title, prompt, zero, fifty, hundred, skills):
    rubric = f'0: {zero}. 50: {fifty}. 100: {hundred}.'
    return {'id': 'suggestion', 'type': 'open_response', 'title': title, 'prompt': prompt,
            'skills': skills, 'rubric': rubric}


def pick_distinct(rng, correct_values, pool, count):
    """Выбрать count значений из pool, не совпадающих с правильными и друг с другом."""
    seen = {str(v) for v in correct_values}
    out = []
    candidates = list(pool)
    rng.shuffle(candidates)
    for value in candidates:
        key = str(value)
        if key not in seen:
            seen.add(key)
            out.append(value)
        if len(out) == count:
            break
    return out


def request_for(kind, specialization, grade, skills, brief):
    return bg.GenerationRequest.model_validate({
        'kind': kind, 'specialization': specialization, 'grade': grade,
        'skills': skills, 'brief': brief})


PROFILE = 'tuned'


def messages_for(request, profile=None):
    """Архивный serving-v3 prompt: сохранённые корпуса не переводятся в новую схему."""
    return bg.request_messages(request, profile or PROFILE, serving=False)


def user_message(request):
    return messages_for(request)[1]


def completion(task):
    """Порядок полей — как в task_json_schema, компактный JSON — как у сервера."""
    schema = bg.task_json_schema(task['type'], task['skills'])
    task = dict(task)
    if 'options' in task:
        # Модель пишет текст и признак верности; ключ и порядок вариантов вычисляет сервер.
        task['options'] = [{'text': o['text'], 'correct': o['id'] in task['answer_key']} for o in task['options']]
    ordered = {key: task[key] for key in schema['properties']}
    return json.dumps(ordered, ensure_ascii=False, separators=(',', ':'))


def validated(task, request):
    """Проверка тем же кодом, что и в продукте; возвращает причину отказа либо None."""
    try:
        raw = json.loads(completion(task))
        bg._checked_generated_shape(raw, request.kind, request.skills)
        bg._checked_task(raw, request)
    except Exception as error:  # noqa: BLE001 - диагностика сборки корпуса
        return f'{type(error).__name__}: {error}'
    return None


def work_from_rubric(open_task_dict):
    """Ход решения семейства = критерий 100 баллов открытого задания: он содержит вычисленные факты."""
    rubric = open_task_dict['rubric']
    text = rubric.rsplit(' 100: ', 1)[-1].strip().rstrip('.')
    return re.sub(r'(?:объяснено|объяснён[а-я]*),? (?:что )?', '', text)


def compose_solution(task, work):
    """Ход решения для типа задания: вычисленные факты, затем вывод об ответе (идёт в JSON до ключа)."""
    if task['type'] == 'single_choice':
        correct = {o['id']: o['text'] for o in task['options']}[task['answer_key'][0]]
        tail = f' Верный вариант: {correct}.'
    elif task['type'] == 'multiple_choice':
        texts = {o['id']: o['text'] for o in task['options']}
        tail = ' Верны: ' + '; '.join(texts[k] for k in task['answer_key']) + '.'
    elif task['type'] == 'numeric':
        unit = task.get('unit') or ''
        tail = f" Ответ: {fmt_num(task['numeric_answer'])}{' ' + unit if unit else ''}."
    else:
        tail = ''
    room = 690 - len(tail)
    base = work if len(work) <= room else work[:room].rsplit(';', 1)[0].rstrip(' ,;')
    if not base:
        base = work[:room]
    return (base.rstrip('.') + '.' + tail).strip()


def make_example(family, request, task, work=None, **extra):
    if work is not None:
        task = {**task, 'solution': compose_solution(task, work)}
    problem = validated(task, request)
    if problem:
        raise ValueError(f'{family}: {problem}')
    return {'family': family, 'kind': request.kind, 'specialization': request.specialization,
            'grade': request.grade, 'skills': request.skills, 'brief': request.brief,
            'system': messages_for(request)[0], 'user': user_message(request),
            'completion': completion(task), **extra}

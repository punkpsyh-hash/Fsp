"""Единая ограниченная схема конструктора, импорта и авторского экспорта."""
import json
import math
import re
import unicodedata
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, StrictInt, create_model, field_validator, model_validator
from .schemas import Input, Grade, Skill, Specialization

TaskType = Literal['single_choice', 'multiple_choice', 'numeric', 'open_response', 'code']


def normalized_option_text(value):
    """Сопоставить визуально одинаковые варианты перед публикацией."""
    value = unicodedata.normalize('NFKC', value).casefold()
    value = ''.join(character for character in value
                    if unicodedata.category(character) not in {'Cf', 'Cc'} or character in '\t\n\r')
    return ' '.join(value.split())


RUBRIC_COLON_SCORE = re.compile(r'(?<!\d)(100|[1-9]?\d)(?!\d)\s*:\s*')
RUBRIC_DASH_SCORE = re.compile(r'(?<!\d)(100|[1-9]?\d)(?!\d)\s*[—–-]\s*')
RUBRIC_WEIGHTED_HEADER = re.compile(
    r'оценка\s+0\s*[—–-]\s*100\s*,?\s*по\s+(\d{1,2})\s+балл(?:а|ов)?\s+за\s+каждый\s+критерий',
    re.IGNORECASE)
RUBRIC_CRITERION = re.compile(r'(?<!\w)\((\d{1,2})\)\s*')


def _scored_sections(value, pattern):
    matches = list(pattern.finditer(value))
    return [(int(match.group(1)), value[match.end():matches[index + 1].start() if index + 1 < len(matches) else None])
            for index, match in enumerate(matches)]


def _has_description(value):
    return any(character.isalpha() for character in value)


def _has_compact_rubric(value):
    sections = _scored_sections(value, RUBRIC_COLON_SCORE)
    zero = next((index for index, (score, text) in enumerate(sections)
                 if score == 0 and _has_description(text)), None)
    full = next((index for index, (score, text) in enumerate(sections)
                 if score == 100 and _has_description(text)), None)
    return (zero is not None and full is not None and zero < full
            and any(zero < index < full and 0 < score < 100 and _has_description(text)
                    for index, (score, text) in enumerate(sections)))


def _has_weighted_legacy_rubric(value):
    header = RUBRIC_WEIGHTED_HEADER.search(value)
    if not header:
        return False
    weight = int(header.group(1))
    if weight <= 0 or 100 % weight:
        return False
    markers = list(RUBRIC_CRITERION.finditer(value, header.end()))
    expected_count = 100 // weight
    if [int(marker.group(1)) for marker in markers] != list(range(1, expected_count + 1)):
        return False
    has_partial = False
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(value)
        sections = _scored_sections(value[marker.end():end], RUBRIC_DASH_SCORE)
        described = {score for score, text in sections if _has_description(text)}
        if 0 not in described or weight not in described:
            return False
        has_partial = has_partial or any(0 < score < weight for score in described)
    return has_partial


def rubric_has_score_anchors(value):
    """Проверить явные уровни 0, частичного и полного (100) ответа.

    Поддерживаются и компактные рубрики ``0:/50:/100:``, и существующие
    аналитические рубрики с нумерованными взвешенными критериями. Одна лишь
    запись диапазона ``0–100`` не описывает критерии крайних оценок.
    """
    return _has_compact_rubric(value) or _has_weighted_legacy_rubric(value)


def plain_markdown(value):
    if re.search(r'<\s*/?\s*[a-zA-Z][^>]*>', value):
        raise ValueError('HTML в условии запрещён; используйте текст или Markdown')
    return value


class Option(Input):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')
    text: str = Field(min_length=1, max_length=2000)


class CodeCase(Input):
    input: str = Field(default='', max_length=16000)
    output: str = Field(default='', max_length=16000)
    setup: str = Field(default='', max_length=32000)

    @field_validator('input', 'output', 'setup')
    @classmethod
    def utf8_budget(cls, value, info):
        maximum = {'input': 16384, 'output': 65536, 'setup': 32768}[info.field_name]
        if len(value.encode('utf-8')) > maximum: raise ValueError(f'UTF-8 поле превышает {maximum} байт')
        return value


class RuntimeLimits(Input):
    wall_seconds: StrictInt = Field(default=3, ge=1, le=3)
    memory_mb: Literal[512] = 512


class Task(Input):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')
    type: TaskType
    title: str = Field(default='', max_length=120)
    prompt: str = Field(default='', max_length=12000)
    skills: list[Skill] = Field(default_factory=list, max_length=6)
    family: str = Field(default='', max_length=80)
    weight: float = Field(default=1, gt=0, le=100, allow_inf_nan=False)
    expected_minutes: StrictInt = Field(default=5, ge=1, le=120)
    options: list[Option] = Field(default_factory=list, max_length=20)
    answer_key: list[str] = Field(default_factory=list, max_length=20)
    partial_credit: bool = False
    numeric_answer: float | None = Field(default=None, allow_inf_nan=False)
    absolute_tolerance: float = Field(default=0, ge=0, le=1000000, allow_inf_nan=False)
    relative_tolerance: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    unit: str = Field(default='', max_length=40)
    rubric: str = Field(default='', max_length=4000)
    answer_limit: StrictInt = Field(default=4000, ge=1, le=16000)
    language: Literal['python', 'javascript', 'sql'] | None = None
    starter_code: str = Field(default='', max_length=32000)
    examples: list[CodeCase] = Field(default_factory=list, max_length=5)
    hidden_tests: list[CodeCase] = Field(default_factory=list, max_length=10)
    runtime_limits: RuntimeLimits = Field(default_factory=RuntimeLimits)

    _text = field_validator('prompt', 'title', 'rubric')(plain_markdown)

    @field_validator('starter_code')
    @classmethod
    def starter_bytes(cls, value):
        if len(value.encode('utf-8')) > 32768: raise ValueError('Шаблон кода превышает 32768 байт UTF-8')
        return value

    @field_validator('hidden_tests')
    @classmethod
    def broker_budget(cls, value):
        encoded = json.dumps([case.model_dump() for case in value], ensure_ascii=False, separators=(',', ':')).encode()
        if len(encoded) > 750000: raise ValueError('Скрытые проверки превышают суммарный бюджет 750000 байт JSON')
        return value

    @model_validator(mode='after')
    def unique_options(self):
        if len({option.id for option in self.options}) != len(self.options):
            raise ValueError('ID вариантов должны различаться')
        if len(set(self.answer_key)) != len(self.answer_key):
            raise ValueError('Ключ содержит повторяющиеся варианты')
        return self


class VersionInput(Input):
    title: str = Field(min_length=2, max_length=120)
    specialization: Specialization = 'backend'
    grade: Grade = 'junior'
    time_limit_minutes: StrictInt = Field(default=60, ge=1, le=240)
    tasks: list[Task] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def unique_tasks(self):
        if len({task.id for task in self.tasks}) != len(self.tasks):
            raise ValueError('ID заданий должны различаться')
        return self


class BankCreate(VersionInput):
    external_id: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_-]{1,120}$')
    scope: Literal['employer', 'platform'] = 'employer'


class VersionSave(VersionInput):
    revision: StrictInt = Field(ge=1)


class Revision(Input):
    revision: StrictInt = Field(ge=1)


class BankDocument(VersionInput):
    schema_version: Literal['fsp-bank-v1'] = 'fsp-bank-v1'
    external_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,120}$')
    scope: Literal['employer', 'platform'] = 'employer'


class AttemptStart(Input):
    version_id: str = Field(max_length=64)


class AnswersSave(Input):
    revision: StrictInt = Field(ge=1)
    answers: dict[str, Any] = Field(max_length=100)


class CodeSubmit(Input):
    task_id: str = Field(max_length=80)
    source: str = Field(min_length=1, max_length=32000)

    @field_validator('source')
    @classmethod
    def source_bytes(cls, value):
        if len(value.encode('utf-8')) > 32768: raise ValueError('Код превышает 32768 байт UTF-8')
        return value


class ReviewInput(Input):
    task_id: str = Field(max_length=80)
    score: StrictInt = Field(ge=0, le=100)
    feedback: str = Field(min_length=2, max_length=4000)


class RunnerResult(Input):
    lease_token: str = Field(min_length=20, max_length=128)
    status: Literal['passed', 'wrong_answer', 'timeout', 'runtime_error', 'system_error']
    passed: StrictInt = Field(ge=0, le=10)
    total: StrictInt = Field(ge=1, le=10)
    duration_ms: StrictInt = Field(ge=0, le=900000)
    runtime_version: str = Field(max_length=120)
    error_code: Literal['runtime_error', 'unsupported_language', 'output_limit', 'runtime_unavailable', 'timeout',
                        'memory_limit', 'system_error', 'execution_timeout', 'payload_limit', 'protocol_limit',
                        'boot_failed', 'job_budget', 'invalid_test_count', 'protocol_error', 'worker_error', 'guest_agent_error'] | None = None


def publication_errors(document):
    errors = []
    if not document['tasks']:
        errors.append({'path': 'tasks', 'message': 'Добавьте хотя бы одно задание'})
    if sum(task['type'] == 'code' for task in document['tasks']) > 10:
        errors.append({'path': 'tasks', 'message': 'В одной попытке допускается максимум 10 заданий кода'})
    for i, task in enumerate(document['tasks']):
        prefix = f'tasks.{i}'
        def error(field, text): errors.append({'path': prefix+'.'+field, 'message': text})
        if not task['title'].strip(): error('title', 'Название обязательно')
        if not task['prompt'].strip(): error('prompt', 'Условие обязательно')
        if not task['skills']: error('skills', 'Укажите проверяемый навык')
        kind = task['type']
        if kind in {'single_choice', 'multiple_choice'}:
            ids = {o['id'] for o in task['options']}
            key = set(task['answer_key'])
            if len(ids) < 2: error('options', 'Необходимы минимум два варианта')
            normalized = [normalized_option_text(option['text']) for option in task['options']]
            if any(not text for text in normalized):
                error('options', 'Варианты ответа не должны быть пустыми')
            elif len(set(normalized)) != len(normalized):
                error('options', 'Варианты ответа не должны повторяться')
            if not key or not key <= ids: error('answer_key', 'Ключ должен ссылаться на варианты')
            if kind == 'single_choice' and len(key) != 1: error('answer_key', 'Выберите ровно один ключ')
            if kind == 'multiple_choice' and not 2 <= len(key) < len(ids):
                error('answer_key', 'Выберите минимум два, но не все варианты')
        elif kind == 'numeric' and task['numeric_answer'] is None:
            error('numeric_answer', 'Укажите числовой эталон')
        elif kind == 'open_response' and not rubric_has_score_anchors(task['rubric']):
            error('rubric', 'Задайте явные критерии для 0, частичного и 100-балльного ответа')
        elif kind == 'code':
            if not task['language']: error('language', 'Выберите язык')
            if not task['examples']: error('examples', 'Добавьте публичный пример')
            if not task['hidden_tests']: error('hidden_tests', 'Добавьте скрытую проверку')
            if len(json.dumps(task['hidden_tests'], ensure_ascii=False, separators=(',', ':')).encode()) > 750000:
                error('hidden_tests', 'Превышен суммарный бюджет скрытых проверок')
            if any(len(case[key].encode()) > limit for case in task['hidden_tests']+task['examples']
                   for key, limit in [('input', 16384), ('setup', 32768), ('output', 65536)]):
                error('hidden_tests', 'UTF-8 проверка превышает лимиты runtime')
            if task['language'] == 'sql':
                for j, case in enumerate(task['hidden_tests']+task['examples']):
                    try:
                        value = json.loads(case['output'])
                        if not isinstance(value, list) or any(not isinstance(row, list) for row in value):
                            raise ValueError()
                    except (ValueError, TypeError):
                        error('hidden_tests', 'SQL-эталон должен быть JSON-массивом строк, каждая строка — массив значений')
                        break
    return errors


def candidate_task(task):
    # Allowlist: новые авторские поля не могут случайно стать публичными.
    fields = ['id', 'type', 'title', 'prompt', 'skills', 'weight', 'expected_minutes',
              'options', 'partial_credit', 'unit', 'rubric', 'answer_limit', 'language',
              'starter_code', 'examples', 'runtime_limits']
    return {key: task[key] for key in fields}


PUBLIC_FIELDS = ['id', 'type', 'title', 'prompt', 'skills', 'weight', 'expected_minutes',
                 'options', 'partial_credit', 'unit', 'rubric', 'answer_limit', 'language',
                 'starter_code', 'examples', 'runtime_limits']
PublicTask = create_model('PublicBankTask', __base__=Input,
                         **{key: (Task.model_fields[key].annotation, Task.model_fields[key]) for key in PUBLIC_FIELDS})


class FieldError(Input):
    path: str
    message: str


class VersionPublic(Input):
    id: str
    bank_id: str
    number: int
    revision: int
    state: Literal['draft', 'published', 'archived']
    scope: Literal['employer', 'platform']
    company_label: str
    title: str
    specialization: Specialization
    grade: Grade
    time_limit_minutes: int
    created_at: datetime
    published_at: datetime | None
    tasks: list[PublicTask]
    validation_errors: list[FieldError]


class VersionAuthor(VersionPublic):
    tasks: list[Task]


class BankView(Input):
    id: str
    title: str
    external_id: str
    scope: Literal['employer', 'platform']
    created_at: datetime
    current_version: VersionAuthor | None
    versions: list[VersionAuthor]


class ImportView(Input):
    id: str
    valid: bool
    errors: list[FieldError]
    warnings: list[str]
    preview: BankDocument | None
    duplicate_bank_id: str | None
    publication_errors: list[FieldError]


class TaskResult(Input):
    task_id: str
    type: TaskType
    score: float | None
    status: Literal['scored', 'pending_review', 'pending_code']
    feedback: str | None


class AttemptResult(Input):
    score: float
    pending_count: int
    completed: bool
    tasks: list[TaskResult]
    scope: Literal['employer', 'platform']
    grade_effect: Literal[False]
    scorer_version: Literal['bank-v1']


class AttemptPublic(Input):
    id: str
    version_id: str
    revision: int
    status: Literal['in_progress', 'pending_review', 'completed']
    deadline: datetime
    created_at: datetime
    submitted_at: datetime | None
    version: VersionPublic
    answers: dict[str, Any]
    result: AttemptResult | None
    candidate_alias: str


class AttemptAuthor(AttemptPublic):
    version: VersionAuthor


class JobResult(Input):
    status: Literal['passed', 'wrong_answer', 'timeout', 'runtime_error', 'system_error']
    passed_tests: int
    total_tests: int
    score: float
    runtime_version: str
    duration_ms: int


class CodeJobView(Input):
    id: str
    task_id: str
    status: Literal['queued', 'running', 'completed', 'failed']
    execution_status: str | None
    result: JobResult | None
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None


class RunnerCase(Input):
    stdin: str
    setup: str
    expected: str | list[list[Any]]


class RunnerJob(Input):
    id: str
    lease_token: str
    language: Literal['python', 'javascript', 'sql']
    source: str
    tests: list[RunnerCase]
    time_limit_seconds: int


class RunnerClaim(Input):
    job: RunnerJob | None


class Saved(Input):
    saved: Literal[True]


def validate_answers(document, answers):
    tasks = {task['id']: task for task in document['tasks']}
    if not set(answers) <= set(tasks):
        raise ValueError('Ответ содержит неизвестное задание')
    for key, value in answers.items():
        task = tasks[key]
        if value is None or value == '': continue
        if task['type'] == 'single_choice':
            if not isinstance(value, str) or value not in {o['id'] for o in task['options']}:
                raise ValueError('Ответ выбора должен ссылаться на один вариант')
        elif task['type'] == 'multiple_choice':
            if not isinstance(value, list) or any(not isinstance(v, str) for v in value) or len(set(value)) != len(value) or not set(value) <= {o['id'] for o in task['options']}:
                raise ValueError('Ответ выбора должен содержать различные ID вариантов')
        elif task['type'] == 'numeric':
            text = str(value).strip().replace(',', '.')
            if task['unit'] and text.endswith(task['unit']): text = text[:-len(task['unit'])].strip()
            try:
                if isinstance(value, (bool, dict, list)) or not math.isfinite(float(text)): raise ValueError()
            except (TypeError, ValueError): raise ValueError('Введите конечное число с указанной единицей')
        else:
            if not isinstance(value, str) or len(value) > (32000 if task['type'] == 'code' else task['answer_limit']):
                raise ValueError('Ответ превышает допустимую длину')
            if task['type'] == 'code' and len(value.encode('utf-8')) > 32768:
                raise ValueError('Код превышает 32768 байт UTF-8')

"""Фиксированное соответствие задач команды ограниченной демо-матрице навыков.

Это словарь требований к подбору, а не доказательство выполнения рабочих задач.
Выбор задачи не изменяет обязательные навыки или веса алгоритма.
"""
from copy import deepcopy

WORK_TASKS_VERSION = 'team-work-v1'
WORK_TASKS = [
    {'id': 'api-development', 'label': 'Разработка API · демо-проверка',
     'description': 'Ограниченная проверка Python и HTTP; проектирование производственного API не подтверждается.',
     'skills': ['python', 'http'], 'specialization': 'backend'},
    {'id': 'sql-reporting', 'label': 'Запросы и отчёты · демо-проверка',
     'description': 'Ограниченная проверка SQL: выборки, связи и агрегации.',
     'skills': ['sql'], 'specialization': 'backend'},
    {'id': 'code-review', 'label': 'Разбор Python-кода · демо-проверка',
     'description': 'Ограниченная проверка чтения Python-кода; опыт ревью в команде не подтверждается.',
     'skills': ['python'], 'specialization': 'backend'},
    {'id': 'access-control', 'label': 'Права доступа API · демо-проверка',
     'description': 'Ограниченная проверка HTTP и проверки доступа; аудит безопасности не подтверждается.',
     'skills': ['http'], 'specialization': 'backend'},
    {'id': 'data-validation', 'label': 'Обработка данных · демо-проверка',
     'description': 'Ограниченная проверка Python и SQL при обработке структурированных данных.',
     'skills': ['python', 'sql'], 'specialization': 'backend'},
    {'id': 'ui-accessibility', 'label': 'Доступные формы · демо-проверка',
     'description': 'Ограниченная проверка HTML и JavaScript: подписи, фокус и обработка ввода.',
     'skills': ['html', 'javascript'], 'specialization': 'frontend'},
    {'id': 'http-client', 'label': 'HTTP-клиент · демо-проверка',
     'description': 'Ограниченная проверка JavaScript и HTTP: запросы и обработка ответов.',
     'skills': ['javascript', 'http'], 'specialization': 'frontend'},
    {'id': 'ui-data', 'label': 'Данные интерфейса · демо-проверка',
     'description': 'Ограниченная проверка преобразований данных в JavaScript.',
     'skills': ['javascript'], 'specialization': 'frontend'},
    {'id': 'api-testing', 'label': 'Проверка API · демо-проверка',
     'description': 'Ограниченная проверка тестирования и HTTP; полнота тестового плана не подтверждается.',
     'skills': ['testing', 'http'], 'specialization': 'qa'},
    {'id': 'data-testing', 'label': 'Проверка данных · демо-проверка',
     'description': 'Ограниченная проверка тестирования и SQL при проверке данных.',
     'skills': ['testing', 'sql'], 'specialization': 'qa'},
    {'id': 'accessible-palette', 'label': 'Доступная палитра · демо-проверка',
     'description': 'Ограниченная проверка расчёта контраста и размеров элементов; художественный вкус не оценивается.',
     'skills': ['ui'], 'specialization': 'design'},
    {'id': 'usability-metrics', 'label': 'Метрики юзабилити · демо-проверка',
     'description': 'Ограниченная проверка расчёта SUS, воронки и закона Фиттса; проведение исследований не подтверждается.',
     'skills': ['ux'], 'specialization': 'design'},
    {'id': 'accessible-markup', 'label': 'Доступная разметка макета · демо-проверка',
     'description': 'Ограниченная проверка HTML: порядок фокуса, имена полей и нативные элементы.',
     'skills': ['html', 'ui'], 'specialization': 'design'},
    {'id': 'boundary-testing', 'label': 'Граничные случаи · демо-проверка',
     'description': 'Ограниченная проверка выбора граничных случаев и ожидаемых результатов.',
     'skills': ['testing'], 'specialization': 'qa'},
]


def catalog(specialization=None):
    """Возвращает независимую копию публичного каталога."""
    if specialization is not None and specialization not in {'backend', 'frontend', 'qa', 'design'}:
        raise ValueError('Неизвестная специализация')
    return deepcopy([task for task in WORK_TASKS if specialization is None or task['specialization'] == specialization])


def resolve(selected_ids, specialization=None):
    """Проверяет ID и специализацию; сохраняет порядок без повторов."""
    available = {task['id']: task for task in catalog(specialization)}
    rows = []
    for task_id in dict.fromkeys(selected_ids):
        if task_id not in available:
            raise ValueError('Задача отсутствует в выбранной специализации')
        rows.append(deepcopy(available[task_id]))
    return rows


def desired_for_tasks(selected_ids, specialization=None):
    return list(dict.fromkeys(skill for task in resolve(selected_ids, specialization) for skill in task['skills']))


def task_matches(verifiedskills, selectedids):
    """Покрытие только переданных подтверждённых навыков, без самооценки/практики."""
    verified = set(verifiedskills)
    rows = []
    for task in resolve(selectedids):
        matched = [skill for skill in task['skills'] if skill in verified]
        missing = [skill for skill in task['skills'] if skill not in verified]
        rows.append({'id': task['id'], 'label': task['label'], 'required_skills': task['skills'],
                     'matched_skills': matched, 'missing_skills': missing,
                     'status': 'covered' if not missing else 'partial' if matched else 'gap'})
    return rows

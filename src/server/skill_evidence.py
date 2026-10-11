"""Безопасная проекция самооценки, формальной демо-оценки и отдельной практики.

Вызывающий код отвечает за доступ к профилю и актуальное согласие публикации.
Проекция не меняет Profile.skills, грейд или правила подбора. Ответы, задания,
код, названия наборов, компании и свободный текст сюда не попадают.
"""
from datetime import timedelta, timezone
import math
from typing import get_args

from sqlalchemy import select

from .assessment import CATALOG, VERSION
from .bank_models import BankAttempt, BankCodeJob, BankReview, BankVersion, TaskBank
from .models import Attempt, TaskResponse
from .schemas import DeclaredSkill, Skill

_ASSESSMENT_SKILLS = frozenset(get_args(Skill))
_DECLARED_IDS = frozenset(get_args(DeclaredSkill))
_LABELS = {'python': 'Python', 'sql': 'SQL', 'javascript': 'JavaScript', 'html': 'HTML',
           'testing': 'Тестирование', 'http': 'HTTP', 'ux': 'UX: исследования и метрики', 'ui': 'UI: визуальный дизайн и доступность',
           'react': 'React', 'vue': 'Vue', 'angular': 'Angular', 'typescript': 'TypeScript', 'nodejs': 'Node.js',
           'nextjs': 'Next.js', 'css': 'CSS', 'tailwind': 'Tailwind CSS', 'fastapi': 'FastAPI', 'django': 'Django',
           'flask': 'Flask', 'go': 'Go', 'java': 'Java', 'kotlin': 'Kotlin', 'csharp': 'C#', 'php': 'PHP', 'rust': 'Rust',
           'spring': 'Spring', 'postgresql': 'PostgreSQL', 'mongodb': 'MongoDB', 'redis': 'Redis', 'kafka': 'Kafka',
           'rabbitmq': 'RabbitMQ', 'graphql': 'GraphQL', 'docker': 'Docker', 'kubernetes': 'Kubernetes', 'linux': 'Linux',
           'cicd': 'CI/CD', 'git': 'Git', 'aws': 'AWS', 'selenium': 'Selenium', 'playwright': 'Playwright',
           'cypress': 'Cypress', 'pytest': 'pytest', 'postman': 'Postman', 'jmeter': 'JMeter', 'figma': 'Figma',
           'prototyping': 'Прототипирование', 'designsystem': 'Дизайн-системы', 'uxresearch': 'UX-исследования',
           'accessibility': 'Доступность (a11y)'}
# Заявленные технологии без оценки: к каким специализациям они относятся (подсказка выбора, не подтверждение).
_DECLARED_SPECS = {
    'angular': ['frontend'], 'react': ['frontend'], 'vue': ['frontend'], 'typescript': ['frontend', 'backend'],
    'nodejs': ['frontend', 'backend'], 'nextjs': ['frontend'], 'css': ['frontend', 'design'], 'tailwind': ['frontend', 'design'],
    'fastapi': ['backend'], 'django': ['backend'], 'flask': ['backend'], 'go': ['backend'], 'java': ['backend'],
    'kotlin': ['backend'], 'csharp': ['backend'], 'php': ['backend'], 'rust': ['backend'], 'spring': ['backend'],
    'postgresql': ['backend', 'qa'], 'mongodb': ['backend'], 'redis': ['backend'], 'kafka': ['backend'],
    'rabbitmq': ['backend'], 'graphql': ['backend', 'frontend'], 'selenium': ['qa'], 'playwright': ['qa', 'frontend'],
    'cypress': ['qa', 'frontend'], 'pytest': ['qa', 'backend'], 'postman': ['qa', 'backend'], 'jmeter': ['qa'],
    'figma': ['design'], 'prototyping': ['design'], 'designsystem': ['design', 'frontend'], 'uxresearch': ['design'],
    'accessibility': ['design', 'frontend', 'qa'],
}
DECLARED_SKILLS = [{'id': skill, 'label': _LABELS[skill],
                    'specializations': [spec for spec, entry in CATALOG.items() if skill in entry['skills']]
                    if skill in _ASSESSMENT_SKILLS else _DECLARED_SPECS.get(skill, ['backend', 'frontend', 'qa'])}
                   for skill in get_args(DeclaredSkill)]

_ASSESSMENT_LIMIT = 'Демо-оценка ограничена заданиями своей версии; независимая калибровка и рабочий опыт не подтверждены.'
_LEGACY_LIMIT = 'Для текущих навыков сохранённого снимка оценки нет: seed/legacy, без детализации баллов и версии.'
_PRACTICE_LIMIT = 'Практика агрегирует баллы заданий с указанным навыком; задачи ≥50% / всего. Она не повышает грейд и не участвует в обязательном фильтре.'
_NO_TASK_SKILLS_LIMIT = 'Общая ручная оценка без навыков отдельных заданий не подтверждает конкретный навык.'


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def _score(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 100


def _assessment(db, profile, skills):
    """Находим снимок именно обновления текущего профиля, а не последнюю попытку.

    API записывает assessed_at и submitted_at двумя последовательными now().
    Их близость проверяется вместе с грейдом, специализацией и всем результатом.
    При неоднозначности остаётся честная legacy-проекция без чисел.
    """
    if not profile.confirmed_grade or not profile.assessed_at:
        return None
    assessed_at = _aware(profile.assessed_at)
    attempts = db.scalars(select(Attempt).where(
        Attempt.candidate_id == profile.user_id, Attempt.specialization == profile.specialization,
        Attempt.grade == profile.confirmed_grade, Attempt.submitted_at >= assessed_at,
        Attempt.submitted_at <= assessed_at + timedelta(seconds=1)))
    matches = []
    versions = {'demo-backend-v1', 'families-v2', 'families-v3', 'families-v4', 'scenarios-v5', VERSION}
    for attempt in attempts:
        if not attempt.created_at or _aware(attempt.created_at) > assessed_at:
            continue
        result = attempt.result
        if not isinstance(result, dict) or result.get('passed') is not True:
            continue
        if not _score(attempt.score) or not _score(result.get('score')) or not _score(profile.test_score):
            continue
        if attempt.score != result['score'] or result['score'] != profile.test_score:
            continue
        result_skills = result.get('skills')
        if not isinstance(result_skills, list) or any(not isinstance(s, str) for s in result_skills):
            continue
        if set(result_skills) != set(skills) or not set(result_skills) <= set(CATALOG[profile.specialization]['skills']):
            continue
        version = result.get('version')
        if not isinstance(version, str) or version not in versions or version != attempt.blueprint_version:
            continue
        breakdown = result.get('breakdown')
        if not isinstance(breakdown, list) or not breakdown:
            continue
        rows, seen = [], set()
        for row in breakdown:
            if not isinstance(row, dict):
                break
            skill, correct, total, score = (row.get(key) for key in ('skill', 'correct', 'total', 'score'))
            if not isinstance(skill, str) or skill not in CATALOG[profile.specialization]['skills'] or skill in seen:
                break
            if type(correct) is not int or type(total) is not int or not 0 <= correct <= total or not 1 <= total <= 100:
                break
            if not _score(score) or score != round(100 * correct / total, 2):
                break
            seen.add(skill)
            rows.append({'skill': skill, 'score': score, 'correct': correct, 'total': total,
                         'version': version, 'assessed_at': profile.assessed_at, 'source': 'assessment'})
        else:
            if set(skills) != {row['skill'] for row in rows if row['score'] >= 50}:
                continue
            if result['score'] != round(100 * sum(row['correct'] for row in rows) / sum(row['total'] for row in rows), 2):
                continue
            if result['score'] < (70 if profile.confirmed_grade == 'junior' else 80):
                continue
            matches.append(rows)
    return matches[0] if len(matches) == 1 else None


def _practice(db, profile):
    groups = {}
    missing_task_skills = db.scalar(select(TaskResponse.id).where(
        TaskResponse.candidate_id == profile.user_id, TaskResponse.reviewed_at.is_not(None),
        TaskResponse.score.is_not(None)).limit(1)) is not None
    attempts = db.execute(select(BankAttempt, BankVersion, TaskBank).join(
        BankVersion, BankAttempt.version_id == BankVersion.id).join(
        TaskBank, BankVersion.bank_id == TaskBank.id).where(
        BankAttempt.candidate_id == profile.user_id, BankAttempt.status == 'completed'))
    for attempt, version, bank in attempts:
        result, document = attempt.result, version.document
        if not isinstance(result, dict) or not isinstance(document, dict) or not attempt.submitted_at:
            continue
        if document.get('specialization') != profile.specialization or bank.scope not in {'platform', 'employer'}:
            continue
        if result.get('completed') is not True or result.get('pending_count') != 0 or not _score(result.get('score')):
            continue
        tasks, scored = document.get('tasks'), result.get('tasks')
        if not isinstance(tasks, list) or not tasks or not isinstance(scored, list) or len(tasks) != len(scored):
            continue
        if any(not isinstance(row, dict) or not isinstance(row.get('task_id'), str) for row in scored):
            continue
        by_id = {row['task_id']: row for row in scored}
        if len(by_id) != len(scored):
            continue
        evaluated = []
        task_ids = set()
        for task in tasks:
            if not isinstance(task, dict) or not isinstance(task.get('id'), str):
                break
            if task['id'] in task_ids:
                break
            task_ids.add(task['id'])
            row = by_id.get(task['id'])
            weight = task.get('weight', 1)
            if not row or row.get('status') != 'scored' or not _score(row.get('score')):
                break
            if isinstance(weight, bool) or not isinstance(weight, (float, int)) or not math.isfinite(weight) or not 0 < weight <= 100:
                break
            task_skills = task.get('skills')
            if not isinstance(task_skills, list) or any(not isinstance(s, str) or s not in _ASSESSMENT_SKILLS for s in task_skills):
                task_skills = []
            evaluated.append((set(task_skills), row['score'], weight))
        else:
            total = sum(score * weight for _, score, weight in evaluated) / sum(weight for _, _, weight in evaluated)
            if round(total, 2) != result['score']:
                continue
            completed_at = _aware(attempt.submitted_at)
            # Последняя финальная проверка может завершиться после отправки.
            reviews = db.scalars(select(BankReview.created_at).where(BankReview.attempt_id == attempt.id))
            jobs = db.scalars(select(BankCodeJob.finished_at).where(
                BankCodeJob.attempt_id == attempt.id, BankCodeJob.status == 'completed', BankCodeJob.finished_at.is_not(None)))
            for timestamp in [*reviews, *jobs]:
                completed_at = max(completed_at, _aware(timestamp))
            source = 'platform-practice' if bank.scope == 'platform' else 'employer-practice'
            for task_skills, score, weight in evaluated:
                if not task_skills:
                    missing_task_skills = True
                for skill in task_skills:
                    group = groups.setdefault((source, skill), {'weighted_score': 0, 'weight': 0,
                                                               'tasks': 0, 'total_tasks': 0, 'completed_at': completed_at})
                    group['weighted_score'] += score * weight
                    group['weight'] += weight
                    group['tasks'] += int(score >= 50)
                    group['total_tasks'] += 1
                    group['completed_at'] = max(group['completed_at'], completed_at)
    rows = [{'skill': skill, 'score': round(group['weighted_score'] / group['weight'], 2),
             'tasks': group['tasks'], 'total_tasks': group['total_tasks'],
             'completed_at': group['completed_at'], 'source': source}
            for (source, skill), group in sorted(groups.items())]
    return rows, missing_task_skills


def skill_evidence(db, profile):
    resume = profile.resume if isinstance(profile.resume, dict) else {}
    declared = resume.get('declared_skills', [])
    declared = list(dict.fromkeys(s for s in declared if isinstance(s, str) and s in _DECLARED_IDS)) if isinstance(declared, list) else []
    profile_skills = profile.skills if isinstance(profile.skills, list) else []
    skills = list(dict.fromkeys(s for s in profile_skills if isinstance(s, str) and s in _ASSESSMENT_SKILLS))
    assessment = _assessment(db, profile, skills)
    limitations = [_ASSESSMENT_LIMIT]
    if assessment is None:
        assessment = [{'skill': skill, 'score': None, 'correct': None, 'total': None, 'version': None,
                       'assessed_at': profile.assessed_at, 'source': 'legacy-assessment'}
                      for skill in skills] if profile.confirmed_grade else []
        if profile.confirmed_grade:
            limitations.append(_LEGACY_LIMIT)
    practice, missing_task_skills = _practice(db, profile)
    if practice:
        limitations.append(_PRACTICE_LIMIT)
    if missing_task_skills:
        limitations.append(_NO_TASK_SKILLS_LIMIT)
    return {'declared': declared[:20], 'assessment': assessment, 'practice': practice, 'limitations': limitations}

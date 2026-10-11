"""Разбор сохранённых форм: эталоны, пропуски и честные ограничения."""
from copy import deepcopy

import pytest

from src.server import assessment
from src.server.assessment import CATALOG, evaluate, questions
from src.server.assessment_feedback import feedback

VERSION = 'families-v4'


@pytest.mark.parametrize('specialization', ('backend', 'frontend', 'qa'))  # исторические версии без дизайна
@pytest.mark.parametrize('grade,threshold,needed', [('junior', 70, 9), ('middle', 80, 10)])
def test_report_matches_existing_grading_in_all_six_blueprints(specialization, grade, threshold, needed):
    form = questions(714, grade, specialization, version="families-v4")
    answers = {}
    for index, row in enumerate(form):
        if index % 3 == 0:
            answers[row['id']] = row['answer']
        elif index % 3 == 1:
            answers[row['id']] = next(option for option in row['options'] if option != row['answer'])
    original = deepcopy((form, answers))
    result = evaluate(714, grade, answers, specialization, version="families-v4", form=form)
    report = feedback(form, answers, grade, VERSION)
    assert (report['threshold'], report['needed_correct']) == (threshold, needed)
    assert (report['correct'], report['total']) == (4, 12)
    assert report['correct'] / report['total'] * 100 == pytest.approx(result['score'], abs=.01)
    assert [{key: skill[key] for key in ('skill', 'correct', 'total', 'score')}
            for skill in report['skills']] == result['breakdown']
    assert [row['id'] for row in report['questions']] == [row['id'] for row in form]
    assert [row['status'] for row in report['questions']] == ['correct', 'incorrect', 'unanswered'] * 4
    for row, question in zip(report['questions'], form):
        assert row['correct_answer'] == question['answer']
        assert row['selected_answer'] == answers.get(question['id'])
        assert 'недоступен' not in row['explanation']
        assert 'Эталон сохранённой формы: ' + question['answer'] in row['explanation']
    assert (form, answers) == original


# Ручные параметры и ответы, не полученные из генератора объяснений.
FAMILIES = [
    ('python-range', 'python', {'n': 17, 'k': 4, 'start': 1}, '4', '4', 'верхнюю границу 17'),
    ('python-state', 'python', {'values': [3, 5], 'appended': [7]}, '15', '3', 'добавляет'),
    ('js-map', 'javascript', {'n': 17, 'k': 4}, '42', '34', 'map(x => x * 2)'),
    ('js-filter', 'javascript', {'n': 17, 'k': 4}, '5', '4', 'от 0 до 16'),
    ('sql-count', 'sql', {'n': 17, 'k': 4}, '13', '13', 'COUNT(*)'),
    ('sql-join', 'sql', {'n': 17, 'k': 4, 'orders_per_user': 3}, '12', '25', 'строк'),
    ('html-focus', 'html', {'n': 17, 'k': 4, 'tab_excluded': 0}, '13', '11', 'Tab'),
    ('html-label', 'html', {'n': 17, 'k': 4, 'aria_named': 0}, '13', '11', 'for'),
    ('test-boundaries', 'testing', {'n': 17, 'k': 4, 'checked_values': [3, 4, 5, 17, 18, 19]}, '18', '3', 'границ'),
    ('test-cases', 'testing', {'n': 17, 'k': 4, 'roles': 1}, '68', '204', 'перемножаются'),
    ('http-retry', 'http', {'distinct_keys': 5, 'repetitions': 3, 'fresh_keys': 0}, '5', '7', 'тем же ключом'),
    ('http-access', 'http', {'n': 17, 'k': 4}, '13', '13', 'отдельно'),
]


def saved_question(family='sql-count', skill='sql', params=None, answer='13'):
    return {'id': 'saved-' + family, 'family': family, 'skill': skill,
            'title': 'Сохранённое условие с явными параметрами',
            'parameters': params if params is not None else {'n': 17, 'k': 4},
            'options': [answer, '999'], 'answer': answer}


@pytest.mark.parametrize('family,skill,params,junior,middle,phrase', FAMILIES)
@pytest.mark.parametrize('grade', ['junior', 'middle'])
def test_all_twelve_families_explain_concrete_parameters(family, skill, params, junior, middle, phrase, grade):
    params = deepcopy(params)
    if grade == 'middle':
        for key in ('tab_excluded', 'aria_named', 'fresh_keys'):
            if key in params:
                params[key] = 2
        if 'roles' in params:
            params['roles'] = 3
    answer = junior if grade == 'junior' else middle
    question = saved_question(family, skill, params, answer)
    explanation = feedback([question], {}, grade, VERSION)['questions'][0]['explanation']
    assert 'недоступен' not in explanation
    assert phrase in explanation
    assert f'Эталон сохранённой формы: {answer}.' in explanation
    assert any(str(value) in explanation for value in params.values())


@pytest.mark.parametrize('grade', ['junior', 'middle'])
@pytest.mark.parametrize('version', ['demo-backend-v1', 'families-v2', 'families-v3'])
def test_legacy_snapshot_is_authoritative_without_inventing_explanations(grade, version, monkeypatch):
    form = questions(34, grade, 'backend', version)
    answers = {row['id']: row['answer'] for row in form}
    monkeypatch.setattr(assessment, 'questions', lambda *args, **kwargs: pytest.fail('snapshot regenerated'))
    report = feedback(form, answers, grade, version)
    assert report['correct'] == report['total'] == len(form)
    assert all(row['status'] == 'correct' for row in report['questions'])
    for row, saved in zip(report['questions'], form):
        assert row['correct_answer'] == saved['answer']
        assert 'Подробный разбор для этого задания недоступен' in row['explanation']


@pytest.mark.parametrize('change', ['version', 'family', 'parameters', 'title', 'empty-title', 'bad-number', 'snapshot-answer'])
def test_unknown_or_inconsistent_snapshot_uses_honest_fallback(change, monkeypatch):
    question = saved_question()
    version = VERSION
    if change == 'version':
        version = 'future-version'
    elif change == 'family':
        question['family'] = 'unknown-family'
    elif change in {'parameters', 'title'}:
        del question[change]
    elif change == 'empty-title':
        question['title'] = ''
    elif change == 'bad-number':
        question['parameters']['n'] = True
    else:
        question['answer'] = '999'
    monkeypatch.setattr(assessment, 'questions', lambda *args, **kwargs: pytest.fail('snapshot regenerated'))
    answer = question['answer']
    row = feedback([question], {question['id']: answer}, 'middle', version)['questions'][0]
    assert row['status'] == 'correct'
    assert row['correct_answer'] == answer
    assert 'недоступен' in row['explanation']
    assert f'Эталон сохранённой формы: {answer}.' in row['explanation']
    assert 'COUNT(email) учитывает' not in row['explanation']


def test_skill_status_is_separate_from_grade_and_topics_target_errors():
    form = [saved_question('sql-count'), saved_question('sql-join', params={'n': 17, 'k': 4, 'orders_per_user': 3}, answer='12')]
    form += [dict(form[0], id='another-count'), dict(form[0], id='last-count')]
    answers = {row['id']: row['answer'] for row in form if row['family'] != 'sql-join'}
    original = deepcopy((form, answers))
    report = feedback(form, answers, 'middle', VERSION)
    skill = report['skills'][0]
    assert (skill['score'], skill['status']) == (75, 'strong')
    assert len(skill['topics']) == 1
    assert 'JOIN' in skill['topics'][0]
    assert 'COUNT' not in skill['topics'][0]
    assert 'Практика не меняет глобальный грейд' in skill['recommendation']
    assert report['correct'] < report['needed_correct']
    answers.pop('another-count')
    assert feedback(form, answers, 'middle', VERSION)['skills'][0]['status'] == 'review'
    report['skills'][0]['topics'].append('Изменённый вывод')
    assert form == original[0]
    assert 'Изменённый вывод' not in feedback(form, answers, 'middle', VERSION)['skills'][0]['topics']


def test_missing_answers_use_full_denominator_and_no_selected_answer():
    form = questions(3, 'junior', 'qa', version="families-v4")
    report = feedback(form, {}, 'junior', VERSION)
    assert (report['correct'], report['total'], report['needed_correct']) == (0, 12, 9)
    assert all(row['status'] == 'unanswered' and row['selected_answer'] is None for row in report['questions'])
    assert all(skill['correct'] == 0 and skill['total'] == 4 and skill['status'] == 'review' for skill in report['skills'])


@pytest.mark.parametrize('answers', [{'foreign-id': '13'}, {'saved-sql-count': 'not-issued'}])
def test_report_rejects_answers_outside_saved_form(answers):
    with pytest.raises(ValueError, match='сохранённой форме'):
        feedback([saved_question()], answers, 'junior', VERSION)


def test_report_requires_private_snapshot_and_known_grade():
    question = saved_question()
    del question['answer']
    with pytest.raises(ValueError, match='эталонами'):
        feedback([question], {}, 'junior', VERSION)
    with pytest.raises(ValueError, match='эталонами'):
        feedback([], {}, 'junior', VERSION)
    with pytest.raises(ValueError, match='грейд'):
        feedback([saved_question()], {}, 'senior', VERSION)

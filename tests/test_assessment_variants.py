"""Эталоны данных, историческая совместимость и перенос готовых ответов.

Хеши v2/v3 получены из исходника коммита 0301b82 до смены VERSION.
Это техническая проверка, не независимая психометрическая калибровка.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from hashlib import sha256
import itertools
import json
import sqlite3

import pytest

from src.server import assessment
from src.server.assessment import CATALOG, evaluate, public_questions, questions

VERSION = 'families-v4'


LEGACY_HASHES = {
    'families-v2': {
        'backend/junior': '3ff563c33d2a2eddbe8b0c300706156629db78cb3d51ab6c8786566872c4f68e',
        'backend/middle': '2c21e9a6432001c5ee374c33bc0a05c565dbcf8b77e5b29629bfa6f227547fe2',
        'frontend/junior': '606577371308f00fb71d627e66b2b1666523aea19bf7cc0a27210bef541554a1',
        'frontend/middle': '4dcbd1548035980a79ef86d296f079c8cd4d82b25da1ab1832aa3fe4862fa41a',
        'qa/junior': 'b04788f80840a16b520adf7f0a78d7d16120e8fa38e5ca77b918268e21d093e9',
        'qa/middle': '08850ef7ebc4f43f24117c741d6c28099b42176f1ac3e86888fcc1e71663cad2',
    },
    'families-v3': {
        'backend/junior': 'bf4445fc249f467e2cf1da1218bc68232c3281a1f761f8f1c18b45e305e656ed',
        'backend/middle': 'bddc7e2a50c09776464a1b7864bc55f6b9c17eec456a3b93355614ea7f6d4cbc',
        'frontend/junior': 'f6a3f8f555f4006b4a8be1aded45d0617b15a5d5c66fe153d2aa6ee4cbdb29ff',
        'frontend/middle': 'fb8091d70fc3395c62cf85b9516ce20564da49a801a2666442cbdeef483738cf',
        'qa/junior': 'bf2adc4ebfa0b6e9c5d22a8f829ad9c521b9bfa643231d7344e27c1b2ed77121',
        'qa/middle': '7752d246c9a428c23556a5dcd1bc61545d075545bf1569b16f711595043e9307',
    },
}


def reference(row, grade):
    """Решение по данным условия, без использования answer генератора."""
    p, family = row['parameters'], row['family']
    middle = grade == 'middle'
    if family == 'python-range':
        count, value = 0, p['start']
        while value < p['n']:
            count += 1
            value += p['k']
        return count
    if family == 'python-state':
        xs = p['values'].copy()
        if middle:
            ys = xs
            ys.extend(p['appended'])
            return len(xs)
        xs.append(p['appended'][0])
        return sum(xs)
    if family == 'js-map':
        values = [p['n'], p['k']]
        if middle:
            values = [v for v in values if v > p['k']]
        return sum(v * 2 for v in values)
    if family == 'js-filter':
        return sum(i % p['k'] == 0 and (not middle or i > 0) for i in range(p['n']))
    if family in {'sql-count', 'sql-join'}:
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE users(id INTEGER, email TEXT)')
            db.executemany('INSERT INTO users VALUES (?, ?)',
                           [(i, None if i < p['k'] else 'synthetic@example.invalid') for i in range(p['n'])])
            if family == 'sql-count':
                return db.execute('SELECT COUNT(email) FROM users').fetchone()[0]
            db.execute('CREATE TABLE orders(user_id INTEGER)')
            db.executemany('INSERT INTO orders VALUES (?)',
                           [(i,) for i in range(p['k']) for _ in range(p['orders_per_user'])])
            join = 'LEFT' if middle else 'INNER'
            return db.execute(f'SELECT COUNT(*) FROM users {join} JOIN orders ON users.id = orders.user_id').fetchone()[0]
    if family == 'html-focus':
        return sum(i >= p['k'] + p['tab_excluded'] for i in range(p['n']))
    if family == 'html-label':
        labeled = set(range(p['k']))
        aria_named = set(range(p['k'], p['k'] + p['aria_named']))
        return len(set(range(p['n'])) - labeled - aria_named)
    if family == 'test-boundaries':
        if middle:
            return sum(not p['k'] <= value <= p['n'] for value in p['checked_values'])
        value = p['n']
        while p['k'] <= value <= p['n']:
            value += 1
        return value
    if family == 'test-cases':
        return sum(1 for _ in itertools.product(range(p['k']), range(p['n']), range(p['roles'])))
    if family == 'http-retry':
        keys = [f'initial-{i}' for i in range(p['distinct_keys']) for _ in range(p['repetitions'])]
        keys += [f'fresh-{i}' for i in range(p['fresh_keys'])]
        return len(set(keys))
    if family == 'http-access':
        grants = set(range(p['k']))
        return sum(company not in grants for company in range(p['n']))
    raise AssertionError(f'Нет независимого эталона: {family}')


@pytest.mark.parametrize('specialization', ('backend', 'frontend', 'qa'))  # исторические семейства без дизайна
@pytest.mark.parametrize('grade', ['junior', 'middle'])
def test_v4_reference_distractors_and_equal_matrix(specialization, grade):
    assert VERSION == 'families-v4'
    answer_values = defaultdict(set)
    for seed in range(100):
        rows = questions(seed, grade, specialization, version="families-v4")
        assert rows == questions(seed, grade, specialization, version="families-v4")
        assert len(rows) == len({q['id'] for q in rows}) == 12
        assert Counter(q['skill'] for q in rows) == Counter({s: 4 for s in CATALOG[specialization]['skills']})
        assert set(Counter(q['family'] for q in rows).values()) == {2}
        for row in rows:
            expected = str(reference(row, grade))
            assert row['answer'] == expected
            assert len(row['options']) == len(set(row['options'])) == 4
            assert row['options'].count(expected) == 1
            assert all(int(option) >= 0 for option in row['options'])
            answer_values[row['id']].add(expected)
        assert all('answer' not in row for row in public_questions(seed, grade, specialization, version="families-v4"))
        answers = {q['id']: str(reference(q, grade)) for q in rows}
        assert evaluate(seed, grade, answers, specialization, version="families-v4")['score'] == 100
        wrong = {q['id']: next(v for v in q['options'] if v != answers[q['id']]) for q in rows}
        assert evaluate(seed, grade, wrong, specialization, version="families-v4")['score'] == 0
    assert all(len(values) > 1 for values in answer_values.values())


@pytest.mark.parametrize('version', LEGACY_HASHES)
@pytest.mark.parametrize('specialization', ('backend', 'frontend', 'qa'))  # исторические семейства без дизайна
@pytest.mark.parametrize('grade', ['junior', 'middle'])
def test_historical_generators_have_exact_saved_content(version, specialization, grade):
    rows = questions(42, grade, specialization, version)
    digest = sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert digest == LEGACY_HASHES[version][specialization + '/' + grade]
    assert len(rows) == (12 if version == 'families-v3' else 6)
    answers = {q['id']: q['answer'] for q in rows}
    assert evaluate(42, grade, answers, specialization, version)['score'] == 100


def test_saved_v3_snapshot_is_graded_without_calling_generator(monkeypatch):
    snapshot = deepcopy(questions(42, 'middle', 'backend', 'families-v3'))
    assert sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest() == LEGACY_HASHES['families-v3']['backend/middle']
    answers = {q['id']: q['answer'] for q in snapshot}
    monkeypatch.setattr(assessment, 'questions', lambda *args, **kwargs: pytest.fail('regenerated saved form'))
    result = evaluate(42, 'middle', answers, 'backend', 'families-v3', form=snapshot)
    assert result['score'] == 100 and result['version'] == 'families-v3'
    assert sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest() == LEGACY_HASHES['families-v3']['backend/middle']


@pytest.mark.parametrize('grade', ['junior', 'middle'])
def test_legacy_v1_still_uses_original_four_questions(grade):
    rows = questions(42, grade, version='demo-backend-v1')
    assert len(rows) == 4
    expected = ({'python-range': '8', 'python-none': 'value is None',
                 'sql-group': 'GROUP BY и COUNT(*)', 'sql-null': 'email IS NULL'} if grade == 'junior'
                else {'python-default': 'Один объект используется между вызовами',
                      'python-retry': 'Идемпотентный ключ и уникальное ограничение',
                      'sql-lock': 'SELECT FOR UPDATE', 'sql-index': 'План выполнения и характер нагрузки'})
    assert {q['id']: q['answer'] for q in rows} == expected
    assert evaluate(42, grade, expected, version='demo-backend-v1')['score'] == 100


@pytest.mark.parametrize('specialization', ('backend', 'frontend', 'qa'))  # исторические семейства без дизайна
@pytest.mark.parametrize('grade', ['junior', 'middle'])
def test_multiple_donors_and_saved_v3_answers_do_not_pass_sample(specialization, grade):
    forms = [questions(seed, grade, specialization, version="families-v4") for seed in range(100)]
    sources = [(VERSION, seed, forms[seed]) for seed in range(20)]
    sources += [('families-v3', seed, questions(seed, grade, specialization, 'families-v3')) for seed in (0, 42, 99)]
    for version, donor_seed, donor in sources:
        values = {q['id']: q['answer'] for q in donor}
        for seed, rows in enumerate(forms):
            if version == VERSION and seed == donor_seed:
                continue
            transferred = {q['id']: values[q['id']] for q in rows if values[q['id']] in q['options']}
            result = evaluate(seed, grade, transferred, specialization, version="families-v4", form=rows)
            assert not result['passed'], (specialization, grade, version, donor_seed, seed, result['score'])


@pytest.mark.parametrize('grade,pass_count', [('junior', 9), ('middle', 10)])
def test_thresholds_and_missing_answers_keep_full_form_denominator(grade, pass_count):
    rows = questions(73, grade, version="families-v4")
    answers = {q['id']: q['answer'] for q in rows[:pass_count]}
    assert evaluate(73, grade, answers, version="families-v4")['passed']
    answers.pop(rows[pass_count - 1]['id'])
    assert not evaluate(73, grade, answers, version="families-v4")['passed']
    assert evaluate(73, grade, {}, version="families-v4")['score'] == 0
    with pytest.raises(ValueError):
        evaluate(73, grade, {'foreign-question': '1'}, version="families-v4")
    with pytest.raises(ValueError):
        evaluate(73, grade, {rows[0]['id']: 'not-issued-option'}, version="families-v4")

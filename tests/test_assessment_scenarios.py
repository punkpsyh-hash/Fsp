"""Сценарии v5: независимые эталоны и конечная техническая диагностика.

Числа donor_probe — не пользовательский пилот и не оценка качества найма.
Код эталона фиксирован автором теста; пользовательский код не исполняется.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from hashlib import sha256
from html.parser import HTMLParser
import json
import sqlite3

import pytest

from src.server import assessment
from src.server.assessment import CATALOG, VERSION, evaluate, public_question_form, questions
from src.server.assessment_feedback import feedback


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(', ', ': '))


def shown_python_result(row):
    """Только тест: исполняет фиксированный авторский фрагмент из генератора.

    В API этот путь отсутствует. Здесь источник — trusted fixtures, не ввод
    кандидата; дополнительно независимый oracle выше проверяет результат.
    """
    source = row['title'].split('\nКак')[0]
    scope = {}
    exec(compile(source, '<trusted-authored-test-fixture>', 'exec'), scope)
    return {'py-selection': lambda: scope['result'], 'py-default': lambda: scope['second'],
            'py-copy': lambda: scope['backup']['queue'], 'py-errors': lambda: scope['failed']}[row['id']]()


class Fragment(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.nodes = []
        self.current = None
        self.feed(source.split('\nКак')[0].split('\nУ каких')[0].split('\nФрагмент')[0])

    def handle_starttag(self, tag, attrs):
        self.current = {'tag': tag, 'attrs': dict(attrs), 'text': ''}
        self.nodes.append(self.current)

    def handle_data(self, data):
        if self.current is not None:
            self.current['text'] += data.strip()

    def handle_endtag(self, tag):
        self.current = None


def oracle(row):
    """Проверяет сохранённые параметры: SQLite или отдельный доверенный обработчик."""
    p, family = row['parameters'], row['family']
    if family.startswith('sql-'):
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE users(id INTEGER, email TEXT)')
            db.execute('CREATE TABLE orders(id INTEGER, user_id INTEGER, amount INTEGER, status TEXT)')
            db.executemany('INSERT INTO users VALUES (?, ?)', [(u['id'], u['email']) for u in p.get('users', [])])
            db.executemany('INSERT INTO orders VALUES (?, ?, ?, ?)',
                           [(o['id'], o['user_id'], o['amount'], o['status']) for o in p.get('orders', [])])
            assert p['query'] in row['title'] and 'SQLite' in row['title']
            result = db.execute(p['query']).fetchall()
            return [v[0] for v in result] if family in {'sql-null-data', 'sql-order-data'} else [list(v) for v in result]
    if family in {'py-selection', 'js-selection'}:
        output = []
        for record in p['records']:
            if not record['active']:
                continue
            if p['middle'] and record['value'] < p['minimum']:
                continue
            output.append(record['id'])
        return output
    if family == 'py-default':
        # Реальные вызовы фиксированного Python-кода, новый default на каждый oracle.
        def remember(value, bucket=[]):
            bucket.append(value)
            return bucket.copy()
        first = remember(p['values'][0])
        second = remember(p['values'][1], []) if p['fresh_second'] else remember(p['values'][1])
        third = remember(p['values'][2])
        assert first is not second and third is not second
        return second
    if family == 'py-copy':
        state = {'queue': [p['original']]}
        backup = deepcopy(state) if p['deep'] else state.copy()
        state['queue'].append(p['appended'])
        return backup['queue']
    if family == 'py-errors':
        failed = []
        for row_data in p['records']:
            try:
                if p['middle'] and row_data['value'] > p['limit']:
                    raise ValueError('limit')
                result = 100 // row_data['value']
                assert result >= 0
            except (ZeroDivisionError, ValueError):
                failed.append(row_data['id'])
        return failed
    if family == 'js-state':
        state = {'items': [p['first']]}
        next_state = dict(state)
        if p['clone']:
            next_state['items'] = list(next_state['items'])
        next_state['items'].append(p['second'])
        return state['items']
    if family == 'js-race':
        result = None
        for completed_id in p['completed']:
            if not p['guarded'] or completed_id == p['started'][-1]:
                result = completed_id
        return result
    if family == 'js-fallback':
        if p['nullish']:
            return p['fallback'] if p['value'] is None else p['value']
        return p['value'] or p['fallback']
    if family == 'http-idempotency-trace':
        ledger, result = {}, []
        for number, request in enumerate(p['events'], 1):
            first = ledger.setdefault(request['key'], (number, request['body']))
            status = 'created' if first[0] == number else 'replay' if first[1] == request['body'] else 'conflict'
            if status == ('conflict' if p['middle'] else 'replay'):
                result.append(number)
        return result
    if family == 'http-contact-revoke':
        last_decision = {}
        for event in p['events']:
            if event['action'] != 'view':
                last_decision[event['company']] = event['action']
        return sorted(company for company, decision in last_decision.items() if decision == 'accept')
    if family == 'http-conditional-write':
        history = [p['initial']]
        result = []
        for number, expected in enumerate(p['conditions'], 1):
            if expected == history[-1]:
                history.append(expected + 1)
                result.append(number)
        return result
    if family == 'http-object-scope':
        if 'offers' in p:   # scenarios-v6: два приглашения
            return [o['id'] for o in p['offers'] if p['role'] == 'employer' and o['owner'] == p['actor']]
        authorized = {p['owner']: {p['offer_id']}}
        return sorted(authorized.get(p['actor'], set())) if p['role'] == 'employer' else []
    if family.startswith('html-'):
        nodes = Fragment(row['title']).nodes
        if family == 'html-tab-order':
            focus = [n for n in nodes if n['tag'] == 'button' and 'disabled' not in n['attrs']
                     and int(n['attrs'].get('tabindex', '0')) >= 0]
            positives = sorted((n for n in focus if int(n['attrs']['tabindex']) > 0),
                               key=lambda n: int(n['attrs']['tabindex']))
            return [n['attrs']['id'] for n in positives + [n for n in focus if n['attrs']['tabindex'] == '0']]
        if family in {'html-accessible-name', 'html-broken-label'}:
            by_id = {n['attrs']['id']: n for n in nodes if 'id' in n['attrs']}
            def name(node):
                attrs = node['attrs']
                if 'aria-labelledby' in attrs:
                    return ' '.join(by_id[key]['text'] for key in attrs['aria-labelledby'].split())
                if 'aria-label' in attrs:
                    return attrs['aria-label']
                return ' '.join(n['text'] for n in nodes if n['tag'] == 'label' and n['attrs'].get('for') == attrs['id'])
            inputs = [n for n in nodes if n['tag'] == 'input']
            return name(inputs[0]) if family == 'html-accessible-name' else [n['attrs']['id'] for n in inputs if not name(n)]
        if family == 'html-native-action':
            return [n['attrs']['id'] for n in nodes if n['tag'] == 'button' and
                    (not p['middle'] or n['attrs'].get('type') == 'button')]
    if family == 'qa-boundary-set':
        allowed = set(range(p['low'], p['high'] + int(p['inclusive'])))
        return [c['id'] for c in p['cases'] if c['value'] not in allowed]
    if family == 'qa-role-matrix':
        def status(case):
            if case['role'] == 'anonymous':
                return 401
            if case['role'] == 'candidate':
                return 403
            return 200 if case['company'] == p['owner'] else 404
        expected = [(c['id'], status(c)) for c in p['cases']]
        return [list(c) for c in expected] if p['middle'] else [key for key, code in expected if code == 200]
    if family == 'qa-transition-trace':
        state = p['initial']
        rejected = []
        for event in p['events']:
            edges = p['transitions'][state]
            if event['action'] in edges:
                state = edges[event['action']]
            else:
                rejected.append(event['id'])
        return rejected
    if family == 'qa-input-contract':
        return [c['id'] for c in p['cases'] if isinstance(c['value'], bool) or
                not isinstance(c['value'], int) or c['value'] < p['minimum'] or c['value'] > p['maximum']]
    if family == 'ui-contrast':
        def lum(color):
            linear = [(c / 255 / 12.92) if c / 255 <= 0.03928 else (((c / 255) + 0.055) / 1.055) ** 2.4
                      for c in (int(color[i:i + 2], 16) for i in (1, 3, 5))]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
        def ratio(pair):
            hi, lo = sorted((lum(pair['fg']), lum(pair['bg'])), reverse=True)
            return (hi + 0.05) / (lo + 0.05)
        return [pair['id'] for pair in p['pairs'] if (3.0 <= ratio(pair) < 4.5 if p['middle'] else ratio(pair) >= 4.5)]
    if family == 'ui-grid':
        column = (p['width'] - 2 * p['padding'] - (p['columns'] - 1) * p['gutter']) / p['columns']
        assert column == int(column)
        return int(p['span'] * column + (p['span'] - 1) * p['gutter'])
    if family == 'ui-type-scale':
        return int(p['base'] * p['ratio'] ** (p['steps'] * p['direction']) + 0.5)
    if family == 'ui-touch-target':
        return [e['id'] for e in p['elements']
                if min(e['w'], e['h']) + 2 * e['pad'] >= p['minimum']]
    if family == 'ux-sus':
        def sus(answers):
            return sum((a - 1) if n % 2 == 0 else (5 - a) for n, a in enumerate(answers)) * 2.5
        mean = round(sum(sus(a) for a in p['responses']) / len(p['responses']), 1)
        return int(mean) if mean == int(mean) else mean
    if family == 'ux-funnel':
        counts = p['counts']
        if p['middle']:
            value = round(counts[-1] / counts[0] * 100, 1)
            return int(value) if value == int(value) else value
        losses = [(counts[i] - counts[i + 1]) / counts[i] for i in range(len(counts) - 1)]
        top = losses.index(max(losses))
        return p['steps'][top] + ' → ' + p['steps'][top + 1]
    if family == 'ux-fitts':
        import math
        bits = math.log2(p['distance'] / p['width'] + 1)
        assert bits == int(bits)
        return int(p['a'] + p['b'] * bits) if p['middle'] else int(bits)
    if family == 'ux-heuristic':
        expected = {0: 'Видимость состояния системы', 1: 'Контроль и свобода пользователя', 2: 'Согласованность и стандарты',
                    3: 'Предотвращение ошибок', 4: 'Помощь в распознавании, диагностике и исправлении ошибок',
                    5: 'Распознавание вместо припоминания', 6: 'Соответствие системы реальному миру',
                    7: 'Справка и документация', 8: 'Эстетика и минимализм', 9: 'Гибкость и эффективность использования'}
        return expected[p['scenario']]
    raise AssertionError('Нет независимого эталона: ' + family)


@pytest.mark.parametrize('specialization', CATALOG)
@pytest.mark.parametrize('grade', ['junior', 'middle'])
@pytest.mark.parametrize('version', ['scenarios-v5', 'scenarios-v6'])
def test_v5_public_oracles_matrix_variants_and_grading(specialization, grade, version):
    assert VERSION == 'scenarios-v6'
    answer_values, positions = defaultdict(set), defaultdict(set)
    for seed in range(100):
        private = questions(seed, grade, specialization, version)
        assert private == questions(seed, grade, specialization, version)
        public = public_question_form(private)
        assert len(private) == len({row['id'] for row in private}) == 12
        assert Counter(row['skill'] for row in private) == Counter({s: 4 for s in CATALOG[specialization]['skills']})
        assert len({row['family'] for row in private}) == 12
        assert all(set(row) == {'id', 'skill', 'title', 'options'} for row in public)
        answers = {}
        for saved, issued in zip(private, public):
            expected = encoded(oracle(saved))
            if saved['family'].startswith('py-'):
                assert encoded(shown_python_result(issued)) == expected
            assert expected == saved['answer']
            assert len(issued['options']) == len(set(issued['options'])) == 4
            assert issued['options'].count(expected) == 1
            assert len(saved['explanation']) > 40 and saved['topic']
            assert 'parameters' not in issued and 'family' not in issued
            answer_values[saved['family']].add(expected)
            positions[saved['family']].add(issued['options'].index(expected))
            answers[saved['id']] = expected
        assert evaluate(seed, grade, answers, specialization, version)['score'] == 100
        wrong = {row['id']: next(v for v in row['options'] if v != answers[row['id']]) for row in private}
        assert evaluate(seed, grade, wrong, specialization, version)['score'] == 0
    assert all(len(values) > 1 for values in answer_values.values())
    assert all(values == {0, 1, 2, 3} for values in positions.values())


def test_public_projection_excludes_any_future_private_fields():
    row = questions(7, 'junior')[0]
    row.update(solution={'answer': row['answer']}, future_private='must stay private')
    row['parameters']['private_oracle'] = {'answer': 'PRIVATE_SENTINEL'}
    projected = public_question_form([row])[0]
    assert set(projected) == {'id', 'skill', 'title', 'options'}
    assert 'PRIVATE_SENTINEL' not in json.dumps(projected)


@pytest.mark.parametrize('grade,needed', [('junior', 9), ('middle', 10)])
def test_v5_thresholds_and_skill_signal_remain_explicit(grade, needed):
    rows = questions(73, grade)
    answers = {q['id']: q['answer'] for q in rows[:needed]}
    result = evaluate(73, grade, answers)
    assert result['passed']
    assert not evaluate(73, grade, {k: v for k, v in list(answers.items())[:-1]})['passed']
    assert evaluate(73, grade, {})['score'] == 0
    chosen = next(skill for skill in CATALOG['backend']['skills'])
    skill_rows = [q for q in rows if q['skill'] == chosen]
    skill_answers = {q['id']: q['answer'] for q in skill_rows[:2]}
    result = evaluate(73, grade, skill_answers)
    assert result['skills'] == [chosen] and not result['passed']
    assert 'не калибрована' in result['limitation'] and 'пилот ещё не проведены' in result['limitation']
    with pytest.raises(ValueError):
        evaluate(73, grade, {'foreign-question': 'anything'})
    with pytest.raises(ValueError):
        evaluate(73, grade, {rows[0]['id']: 'not-issued-option'})


def test_v5_snapshot_drives_grading_explanations_and_topics(monkeypatch):
    snapshot = deepcopy(questions(17, 'middle', 'qa'))
    snapshot[0]['answer'] = next(option for option in snapshot[0]['options'] if option != snapshot[0]['answer'])
    snapshot[0]['explanation_answer'] = snapshot[0]['answer']
    snapshot[0]['explanation'] = 'Разбор из сохранённой версии, неизменный после обновления генератора.'
    snapshot[0]['topic'] = 'Тема сохранённой версии'
    original = deepcopy(snapshot)
    answers = {q['id']: q['answer'] for q in snapshot}
    monkeypatch.setattr(assessment, 'questions', lambda *a, **kw: pytest.fail('regenerated saved snapshot'))
    assert evaluate(999, 'middle', answers, 'qa', form=snapshot)['score'] == 100
    report = feedback(snapshot, answers, 'middle', VERSION)
    assert report['questions'][0]['explanation'].startswith(snapshot[0]['explanation'])
    assert report['questions'][0]['correct_answer'] == snapshot[0]['answer']
    assert any(snapshot[0]['topic'] in skill['topics'] for skill in report['skills'])
    assert snapshot == original
    del snapshot[0]['explanation']
    assert 'недоступен' in feedback(snapshot, answers, 'middle', VERSION)['questions'][0]['explanation']


def test_v5_inconsistent_explanation_key_uses_honest_fallback():
    snapshot = deepcopy(questions(17, 'middle', 'qa'))
    old_reason = snapshot[0]['explanation']
    snapshot[0]['answer'] = next(option for option in snapshot[0]['options'] if option != snapshot[0]['answer'])
    answers = {q['id']: q['answer'] for q in snapshot}
    assert evaluate(17, 'middle', answers, 'qa', form=snapshot)['score'] == 100
    row = feedback(snapshot, answers, 'middle', VERSION)['questions'][0]
    assert row['correct_answer'] == snapshot[0]['answer'] and row['status'] == 'correct'
    assert 'недоступен' in row['explanation'] and old_reason not in row['explanation']
    assert 'explanation_answer' not in public_question_form(snapshot)[0]


V4_DIGESTS = {
    'backend/junior': 'f99c1df02f2ee46f002cffc05521056bd665c460dddafc8d2435483dc957db49',
    'backend/middle': '320644620c65bf8864fc5c6ff4b8b781e3e145bc8aaa4cd189693e8b7de4daf3',
    'frontend/junior': '87cb74c198d4346c1f29be499d65952291aeaf915b73a37a2368db3d2abcfd46',
    'frontend/middle': '35971fac3b2bbc7e4ae3ee25ed09cb3356ff7f27d4687c86908d143916465793',
    'qa/junior': '08e1333fa277c58b1475d403f415bfc199ff2c605b3b6f7384fb4465d17344f6',
    'qa/middle': '9e584c283db20208d7b3020284780cba6b2a8d6d3f0016eab96d2d7a52e45a28',
}


@pytest.mark.parametrize('specialization', ('backend', 'frontend', 'qa'))  # families-v4 дизайн не поддерживает
@pytest.mark.parametrize('grade', ['junior', 'middle'])
def test_v4_without_snapshot_preserves_exact_form_and_feedback(specialization, grade):
    rows = questions(42, grade, specialization, version='families-v4')
    digest = sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert digest == V4_DIGESTS[specialization + '/' + grade]
    answers = {q['id']: q['answer'] for q in rows}
    assert evaluate(42, grade, answers, specialization, version='families-v4')['score'] == 100
    assert all('недоступен' not in q['explanation'] for q in feedback(rows, answers, grade, 'families-v4')['questions'])


def donor_probe(donor_seeds=range(20), receiver_seeds=range(100, 200)):
    """Два ограниченных способа переноса, получатель/донор имеют разные seed.

    literal копирует текст эталона по family; отсутствующий вариант пропущен.
    position копирует номер правильного варианта по family (порядок shuffled).
    Это моделирует опубликованный ключ; решатель по правилам способен пройти.
    """
    records = []
    for specialization in CATALOG:
        for grade in ('junior', 'middle'):
            donors = [questions(seed, grade, specialization) for seed in donor_seeds]
            receivers = [questions(seed, grade, specialization) for seed in receiver_seeds]
            for strategy in ('literal', 'position'):
                scores = []
                passes = 0
                for donor in donors:
                    key = {q['family']: q['answer'] if strategy == 'literal' else q['options'].index(q['answer'])
                           for q in donor}
                    for form in receivers:
                        copied = {q['id']: key[q['family']] if strategy == 'literal' else q['options'][key[q['family']]]
                                  for q in form if strategy != 'literal' or key[q['family']] in q['options']}
                        result = evaluate(0, grade, copied, specialization, form=form)
                        scores.append(result['score'])
                        passes += result['passed']
                records.append({'specialization': specialization, 'grade': grade, 'strategy': strategy,
                                'pairs': len(scores), 'passes': passes, 'maximum_score': max(scores),
                                'mean_score': round(sum(scores) / len(scores), 2)})
    return {'version': VERSION, 'donor_seeds': [min(donor_seeds), max(donor_seeds)],
            'receiver_seeds': [min(receiver_seeds), max(receiver_seeds)], 'results': records,
            'limitation': 'Конечная синтетическая диагностика копирования ответов; не защита от решателя, не человеческий пилот и не калибровка сложности.'}


def test_donor_probe_reports_observations_without_universal_claims():
    report = donor_probe(range(3), range(100, 110))
    assert len(report['results']) == 16
    assert all(row['pairs'] == 30 and 0 <= row['passes'] <= row['pairs'] and
               0 <= row['mean_score'] <= row['maximum_score'] <= 100 for row in report['results'])


def test_v5_api_active_and_expired_views_never_publish_private_fields(client):
    from datetime import timedelta
    from tests.test_api import register
    from src.server.models import Attempt, now
    register(client, name='v5-projection')
    response = client.post('/api/v1/assessments/attempts', json={'specialization': 'backend', 'grade': 'junior'})
    assert response.status_code == 201
    attempt = response.json()
    with client.app.state.factory() as db:
        private = db.get(Attempt, attempt['id']).question_form
    assert all(len(q['id']) == 24 and q['family'] not in q['id'] for q in private)
    path = '/api/v1/assessments/attempts/' + attempt['id']
    for view in [attempt, client.get(path).json(), client.get('/api/v1/candidate/active-assessment').json()]:
        assert view['feedback'] is None
        assert all(set(q) == {'id', 'skill', 'title', 'options'} for q in view['questions'])
        assert [q['id'] for q in view['questions']] == [q['id'] for q in private]
    draft = client.put(path + '/draft', json={'answers': {}, 'expected_revision': 0}).json()
    assert draft['feedback'] is None and all('explanation' not in q for q in draft['questions'])
    with client.app.state.factory() as db:
        db.get(Attempt, attempt['id']).created_at = now() - timedelta(minutes=61)
        db.commit()
    expired = client.get(path).json()
    assert expired['feedback'] is None and all('explanation' not in q for q in expired['questions'])


# Reuse the real API's isolated fixture; no running app requests.
from tests.test_api import client


def _digest(version):
    rows = [questions(seed, grade, spec, version) for seed in range(60)
            for grade in ('junior', 'middle') for spec in ('backend', 'frontend', 'qa')]   # исходные направления; design добавлен позже
    return sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def test_v5_generator_output_is_unchanged_and_v6_differs():
    # Хеш получен из исходника коммита 6e518e0 до добавления scenarios-v6.
    assert _digest('scenarios-v5') == '78522971455d52ca81d89826e922a9e6462c11316507454beed44200203fc147'
    assert _digest('scenarios-v6') != _digest('scenarios-v5')


def test_v6_does_not_reveal_answer_by_option_length():
    # Раньше самый короткий вариант был верным в 29–38% форм; допускаем не выше 31%.
    hits = total = 0
    for seed in range(150):
        for grade in ('junior', 'middle'):
            for spec in CATALOG:
                for q in questions(seed, grade, spec, 'scenarios-v6'):
                    total += 1
                    hits += min(q['options'], key=len) == q['answer']
    assert hits / total < 0.31


def test_v6_has_no_strongly_exploitable_family():
    # Аудит по семействам: ни одна простая стратегия (позиция, длина, сходство, числа условия) не должна
    # давать в v6 верный ответ заметно чаще случайных 25% (в v5 доходило до 77%).
    from scripts.validate_retest import STRATEGIES
    from collections import defaultdict
    hits = defaultdict(lambda: defaultdict(int))
    totals = defaultdict(int)
    for seed in range(100):
        for grade in ('junior', 'middle'):
            for spec in CATALOG:
                for q in questions(seed, grade, spec, 'scenarios-v6'):
                    key = (q['family'], grade)
                    totals[key] += 1
                    for name, pick in STRATEGIES.items():
                        hits[key][name] += pick(q) == q['answer']
    worst = max(hits[key][name] / totals[key] for key in totals for name in STRATEGIES)
    assert worst < 0.62, worst

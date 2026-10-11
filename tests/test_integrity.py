"""Сигналы добросовестности: пороги, серверный темп, удержание подтверждения, приватность."""
from src.server import integrity as integ
from src.server.assessment import questions
from src.server.models import Attempt, Profile
import pytest
from tests.test_api import client, login  # noqa: F401  (fixture)


def event(kind, t, **extra):
    return {'type': kind, 't': t, **extra}


def state_with(events):
    return integ.record_events(integ.new_state(), events)


def test_single_tab_leave_is_not_a_signal():
    result = integ.assess(state_with([event('hidden', 5000), event('visible', 9000, d=4000)]))
    assert result['level'] == 'clean' and result['signals'] == []


def test_repeated_leaves_and_copies_raise_levels():
    leaves = [e for i in range(4) for e in (event('hidden', 10_000 * i), event('visible', 10_000 * i + 2000, d=2000))]
    assert integ.assess(state_with(leaves))['level'] == 'review'
    copies = [event('copy', 1000 * i) for i in range(4)]
    result = integ.assess(state_with(copies))
    assert result['level'] == 'flagged' and result['signals'][0]['code'] == 'clipboard_copies'


def test_answers_right_after_returning_is_detected():
    log = []
    for i in range(5):
        base = 60_000 * i
        log += [event('hidden', base), event('visible', base + 20_000, d=20_000), event('answer', base + 25_000, q=f'q{i}')]
    result = integ.assess(state_with(log))
    assert result['metrics']['answers_after_return'] == 5
    assert any(s['code'] == 'answers_after_return' for s in result['signals'])


def test_monitoring_gap_when_client_goes_silent():
    state = state_with([event('heartbeat', 0), event('heartbeat', 15_000), event('heartbeat', 400_000)])
    assert integ.assess(state)['metrics']['monitoring_gap_seconds'] == 370


def test_pace_uses_server_times_and_bulk_is_not_misread_as_speed():
    state = integ.new_state()
    answers = {}
    for index in range(8):
        before = dict(answers)
        answers[f'q{index}'] = 'x'
        integ.note_answers(state, before, answers, 20 + index * 3)  # 3 с на вопрос
    result = integ.assess(state)
    assert result['level'] == 'flagged' and result['metrics']['median_seconds_per_answer'] == 3.0
    bulk = integ.note_answers(integ.new_state(), {}, {f'q{i}': 'x' for i in range(10)}, 300)
    result = integ.assess(bulk)
    assert result['level'] == 'review' and 'median_seconds_per_answer' not in result['metrics']


def test_slow_human_pace_is_clean():
    state, answers = integ.new_state(), {}
    for index in range(8):
        before = dict(answers)
        answers[f'q{index}'] = 'x'
        integ.note_answers(state, before, answers, 60 + index * 55)
    assert integ.assess(state)['level'] == 'clean'


def start(client, spec='backend'):
    r = client.post('/api/v1/assessments/attempts', json=dict(specialization=spec, grade='junior'))
    assert r.status_code == 201, r.text
    return r.json()


def correct_answers(client, attempt_id):
    with client.app.state.factory() as db:
        a = db.get(Attempt, attempt_id)
        return {q['id']: q['answer'] for q in a.question_form}


def test_events_endpoint_validation_ownership_and_privacy(client):
    login(client, 'candidate-a')
    attempt = start(client)
    path = f"/api/v1/assessments/attempts/{attempt['id']}/integrity"
    ok = client.post(path, json={'events': [event('hidden', 100), event('visible', 900, d=800)]})
    assert ok.status_code == 202 and ok.json() == {'recorded': 2}
    for bad in ({'events': []}, {'events': [event('keylog', 1)]}, {'events': [event('copy', -1)]},
                {'events': [event('copy', 1, text='secret')]}, {'events': [event('copy', 1)] * 101}):
        assert client.post(path, json=bad).status_code == 422
    with client.app.state.factory() as db:
        stored = db.get(Attempt, attempt['id']).integrity
    assert stored['counts'] == {'hidden': 1, 'visible': 1}
    assert 'secret' not in str(stored)
    login(client, 'candidate-b')
    assert client.post(path, json={'events': [event('copy', 1)]}).status_code == 404
    login(client, 'employer-x')
    assert client.post(path, json={'events': [event('copy', 1)]}).status_code == 403


def test_explicit_demo_mode_shows_signals_without_holding(client, monkeypatch):
    monkeypatch.setenv('FSP_INTEGRITY_ENFORCE', '0')
    login(client, 'candidate-a')
    attempt = start(client)
    client.post(f"/api/v1/assessments/attempts/{attempt['id']}/integrity",
                json={'events': [event('copy', 100 * i) for i in range(5)]})
    result = client.post(f"/api/v1/assessments/attempts/{attempt['id']}/submit",
                         json={'answers': correct_answers(client, attempt['id'])}).json()
    assert result['integrity']['level'] == 'flagged' and result['integrity']['enforced'] is False
    assert result['integrity']['hold'] is False and result['confirmed'] is True and result['passed'] is True


def test_enforced_flag_holds_confirmation_and_allows_immediate_recheck(client, monkeypatch):
    monkeypatch.setenv('FSP_INTEGRITY_ENFORCE', '1')
    login(client, 'candidate-a')
    attempt = start(client)
    client.post(f"/api/v1/assessments/attempts/{attempt['id']}/integrity",
                json={'events': [event('copy', 100 * i) for i in range(5)]})
    result = client.post(f"/api/v1/assessments/attempts/{attempt['id']}/submit",
                         json={'answers': correct_answers(client, attempt['id'])}).json()
    assert result['passed'] is True and result['confirmed'] is False and result['integrity']['hold'] is True
    with client.app.state.factory() as db:
        profile = db.get(Profile, db.get(Attempt, attempt['id']).candidate_id)
        assert profile.integrity_level != 'flagged'
    again = client.post('/api/v1/assessments/attempts', json=dict(specialization='backend', grade='junior'))
    assert again.status_code == 201 and again.json()['id'] != attempt['id']


@pytest.mark.parametrize('setting', [None, '1'])
def test_strict_immediate_bulk_submission_holds_grade(client, monkeypatch, setting):
    if setting is None:
        monkeypatch.delenv('FSP_INTEGRITY_ENFORCE')
    else:
        monkeypatch.setenv('FSP_INTEGRITY_ENFORCE', setting)
    login(client, 'candidate-a')
    attempt = start(client)
    result = client.post(f"/api/v1/assessments/attempts/{attempt['id']}/submit",
                         json={'answers': correct_answers(client, attempt['id'])}).json()
    assert result['passed'] and not result['confirmed'] and result['integrity']['hold']
    assert any(s['code'] == 'bulk_answers' and s['level'] == 'flagged'
               for s in result['integrity']['signals'])


def test_bulk_after_normal_elapsed_time_does_not_claim_impossible_speed():
    state = integ.note_answers(integ.new_state(), {}, {f'q{i}': 'x' for i in range(12)}, 300)
    state = integ.record_events(state, [event('heartbeat', 300_000)], 300)
    result = integ.assess(state, 300)
    assert result['level'] == 'review'
    assert 'median_seconds_per_answer' not in result['metrics']


def test_strict_repeated_held_recheck_cannot_harvest_unlimited_forms(client, monkeypatch):
    monkeypatch.setenv('FSP_INTEGRITY_ENFORCE', '1')
    login(client, 'candidate-a')
    for _ in range(2):
        attempt = start(client)
        client.post(f"/api/v1/assessments/attempts/{attempt['id']}/integrity",
                    json={'events': [event('copy', 100 * i) for i in range(5)]})
        result = client.post(f"/api/v1/assessments/attempts/{attempt['id']}/submit",
                             json={'answers': correct_answers(client, attempt['id'])}).json()
        assert result['integrity']['hold'] and not result['confirmed']
    third = client.post('/api/v1/assessments/attempts', json=dict(specialization='backend', grade='junior'))
    assert third.status_code == 409


def test_event_budget_does_not_disable_later_copy_detection(client, monkeypatch):
    monkeypatch.setenv('FSP_INTEGRITY_ENFORCE', '1')
    login(client, 'candidate-a')
    attempt = start(client)
    path = f"/api/v1/assessments/attempts/{attempt['id']}/integrity"
    for _ in range(15):
        assert client.post(path, json={'events': [event('heartbeat', 1)] * 100}).status_code == 202
    ack = client.post(path, json={'events': [event('copy', 100 * i) for i in range(5)]})
    assert ack.json()['recorded'] == 5
    with client.app.state.factory() as db:
        state = db.get(Attempt, attempt['id']).integrity
    assert integ.assess(state)['metrics']['clipboard_copies'] == 5


def test_telemetry_rate_limit_stops_flood_then_recovers(client, monkeypatch):
    from importlib import import_module
    app_module = import_module('src.server.app')
    clock = [1000.0]
    monkeypatch.setattr(app_module, 'monotonic', lambda: clock[0])
    login(client, 'candidate-a')
    attempt = start(client)
    path = f"/api/v1/assessments/attempts/{attempt['id']}/integrity"
    for _ in range(60):
        assert client.post(path, json={'events': [event('heartbeat', 1)]}).status_code == 202
    limited = client.post(path, json={'events': [event('copy', 1)]})
    assert limited.status_code == 429 and limited.headers['Retry-After'] == '60'
    clock[0] += 61
    assert client.post(path, json={'events': [event('copy', 1)]}).json()['recorded'] == 1


def test_telemetry_budget_is_per_authenticated_user_not_shared_ip(client):
    login(client, 'candidate-a')
    first = start(client)
    path = f"/api/v1/assessments/attempts/{first['id']}/integrity"
    for _ in range(60):
        assert client.post(path, json={'events': [event('heartbeat', 1)]}).status_code == 202
    assert client.post(path, json={'events': [event('heartbeat', 1)]}).status_code == 429
    login(client, 'candidate-b')
    second = start(client)
    assert client.post(f"/api/v1/assessments/attempts/{second['id']}/integrity",
                       json={'events': [event('heartbeat', 1)]}).status_code == 202


def test_unauthorized_telemetry_does_not_charge_candidate_budget(client):
    for _ in range(60):
        assert client.post('/api/v1/assessments/attempts/nonexistent/integrity',
                           json={'events': [event('heartbeat', 1)]}).status_code == 401
    login(client, 'candidate-a')
    attempt = start(client)
    assert client.post(f"/api/v1/assessments/attempts/{attempt['id']}/integrity",
                       json={'events': [event('heartbeat', 1)]}).status_code == 202

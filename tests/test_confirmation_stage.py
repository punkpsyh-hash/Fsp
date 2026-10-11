"""Подтверждающая форма: результат у порога не принимается и не сжигает попытку, итог считается по двум формам."""
from datetime import timedelta

from src.server import app as app_module
from src.server.models import Attempt, GradeEvent, Profile, now
from tests.test_api import client, register  # noqa: F401  (fixture)


def start(client, grade='junior'):
    return client.post('/api/v1/assessments/attempts', json=dict(specialization='backend', grade=grade))


def answers_with_correct(client, attempt_id, correct):
    """Ответы, в которых верны ровно `correct` из 12 заданий."""
    with client.app.state.factory() as db:
        form = db.get(Attempt, attempt_id).question_form
    result = {}
    for index, question in enumerate(form):
        right = index < correct
        result[question['id']] = question['answer'] if right else next(o for o in question['options'] if o != question['answer'])
    return result


def submit(client, attempt, correct):
    r = client.post(f"/api/v1/assessments/attempts/{attempt['id']}/submit",
                    json={'answers': answers_with_correct(client, attempt['id'], correct)})
    assert r.status_code == 200, r.text
    return r.json()


def profile(client):
    return client.get('/api/v1/candidate/profile').json()


def test_borderline_first_result_is_inconclusive_and_does_not_burn_the_attempt(client):
    register(client, 'stage-a')
    first = start(client).json()
    result = submit(client, first, 9)                       # 75 баллов при пороге 70: в полосе ±6
    assert result['needs_confirmation'] is True and result['passed'] is False and result['confirmed'] is False
    assert result['stage'] == 1 and profile(client)['confirmed_grade'] is None
    with client.app.state.factory() as db:
        assert db.query(GradeEvent).count() == 0
    second = start(client)                                  # без ожидания 14 суток
    assert second.status_code == 201
    assert second.json()['context']['stage'] == 2 and second.json()['context']['parent'] == first['id']


def test_second_form_decides_by_the_average_of_both_forms(client):
    register(client, 'stage-b')
    first = start(client).json()
    submit(client, first, 9)                                # 75
    second = start(client).json()
    final = submit(client, second, 12)                      # 100: среднее 87,5
    assert final['stage'] == 2 and final['stage_scores'] == [75.0, 100.0] and final['score'] == 87.5
    assert final['passed'] is True and final['confirmed'] is True and not final.get('needs_confirmation')
    assert profile(client)['confirmed_grade'] == 'junior'
    assert sum(row['total'] for row in final['breakdown']) == 24
    evidence = profile(client)['skill_evidence']['assessment']
    assert {row['skill']: row['total'] for row in evidence} == {'python': 8, 'sql': 8, 'http': 8}
    assert start(client).status_code == 409                 # дальше обычные 14 суток


def test_second_form_can_also_reject(client):
    register(client, 'stage-c')
    first = start(client).json()
    submit(client, first, 9)                                # 75
    final = submit(client, start(client).json(), 6)         # 50: среднее 62,5 < 70
    assert final['passed'] is False and final['confirmed'] is False and final['score'] == 62.5
    assert profile(client)['confirmed_grade'] is None
    assert start(client).status_code == 409


def test_confirmation_expires_after_24_hours(client):
    register(client, 'stage-d')
    first = start(client).json()
    submit(client, first, 9)
    with client.app.state.factory() as db:
        attempt = db.get(Attempt, first['id'])
        attempt.submitted_at = now() - timedelta(hours=25)
        db.commit()
    fresh = start(client)
    assert fresh.status_code == 201 and 'stage' not in fresh.json()['context']


def test_clear_results_are_not_affected_and_band_can_be_disabled(client, monkeypatch):
    register(client, 'stage-e')
    clear = submit(client, start(client).json(), 12)
    assert clear['confirmed'] is True and not clear.get('needs_confirmation')
    monkeypatch.setattr(app_module, 'CONFIRMATION_BAND', 0)
    register(client, 'stage-f')
    plain = submit(client, start(client).json(), 9)
    assert plain['passed'] is True and plain['confirmed'] is True and not plain.get('needs_confirmation')

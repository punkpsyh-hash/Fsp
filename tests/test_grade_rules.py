"""Смена грейда: повышение ограничено 90 сутками, понижение по желанию кандидата без ожидания."""
from datetime import timedelta
from datetime import datetime, timezone

from src.domain import grade_result
from src.server.assessment import questions
from src.server.models import Attempt, Profile, now
from tests.test_api import client, login  # noqa: F401  (fixture)

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def test_domain_downgrade_is_allowed_inside_cooldown_but_upgrade_is_not():
    recent = NOW - timedelta(days=3)
    assert grade_result('middle', 'junior', True, recent, NOW) == 'junior'
    try:
        grade_result('junior', 'middle', True, recent, NOW)
    except ValueError as error:
        assert str(error) == 'grade_cooldown'
    else:
        raise AssertionError('повышение внутри 90 суток должно быть запрещено')


def set_profile(client, **values):
    with client.app.state.factory() as db:
        p = db.get(Profile, 'demo-candidate-a')
        for key, value in values.items():
            setattr(p, key, value)
        db.commit()


def solve(client, attempt):
    with client.app.state.factory() as db:
        a = db.get(Attempt, attempt['id'])
        answers = {q['id']: q['answer'] for q in a.question_form}
    return client.post(f"/api/v1/assessments/attempts/{attempt['id']}/submit", json={'answers': answers})


def test_api_lower_grade_can_be_taken_at_once_and_restarts_upgrade_limit(client):
    login(client, 'candidate-a')
    set_profile(client, confirmed_grade='middle', grade_changed_at=now() - timedelta(days=2))
    started = client.post('/api/v1/assessments/attempts', json={'specialization': 'backend', 'grade': 'junior'})
    assert started.status_code == 201
    result = solve(client, started.json()).json()
    assert result['confirmed'] is True
    assert client.get('/api/v1/candidate/profile').json()['confirmed_grade'] == 'junior'
    again = client.post('/api/v1/assessments/attempts', json={'specialization': 'backend', 'grade': 'middle'})
    assert again.status_code == 409 and 'понизить уровень можно сразу' in again.json()['message']


def test_cooldown_reached_after_start_keeps_the_result_instead_of_failing_submit(client):
    login(client, 'candidate-a')
    set_profile(client, confirmed_grade='junior', grade_changed_at=now() - timedelta(days=100))
    started = client.post('/api/v1/assessments/attempts', json={'specialization': 'backend', 'grade': 'middle'})
    assert started.status_code == 201
    set_profile(client, grade_changed_at=now() - timedelta(days=1))   # гонка: смена грейда случилась после старта
    response = solve(client, started.json())
    assert response.status_code == 200
    result = response.json()
    assert result['passed'] is True and result['confirmed'] is False and result['cooldown'] is True
    assert client.get('/api/v1/candidate/profile').json()['confirmed_grade'] == 'junior'
    assert client.get(f"/api/v1/assessments/attempts/{started.json()['id']}").json()['result']['score'] == 100

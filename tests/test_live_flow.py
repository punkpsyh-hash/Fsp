"""Сквозной путь «как на настоящем сайте»: оба участника регистрируются сами, без демо-входа."""
from fastapi.testclient import TestClient

from tests.test_api import client, invite, register  # noqa: F401 - фикстура client
from tests.test_product import complete_attempt, update_profile


def test_designer_and_employer_register_and_complete_the_whole_path(client):
    employer = TestClient(client.app)   # отдельный «браузер» со своей сессией и cookie
    # Участник: регистрация, свои данные, оценка по направлению «дизайн», публикация.
    register(client, 'designer-live')
    assert update_profile(client, 'design', salary_min=120000, formats=['remote', 'hybrid'],
                          contact='designer-live@example.invalid').status_code == 200
    result = complete_attempt(client, 'design')
    assert result['passed'] and len(result['breakdown']) == 3
    assert {row['skill'] for row in result['breakdown']} == {'ux', 'ui', 'html'}
    profile = client.get('/api/v1/candidate/profile').json()
    assert profile['specialization'] == 'design' and profile['confirmed_grade'] == 'junior'
    assert client.post('/api/v1/candidate/consents', json={'published': True}).status_code == 200
    candidate_id = profile['id']

    # Работодатель: отдельная регистрация, профиль компании, потребность, подборка.
    register(employer, 'employer-live', role='employer')
    assert employer.put('/api/v1/company/profile', json=dict(
        name='Студия Живой стенд', description='Синтетическая студия для проверки сквозного пути.',
        industry='Дизайн', contact='studio@example.invalid')).status_code == 200
    need = employer.post('/api/v1/company/needs', json=dict(
        title='Поиск UI/UX дизайнера', description='Интерфейсы, доступность и метрики юзабилити.',
        specialization='design', grade='junior', must_skills=['ui'], desired_skills=['ux', 'html'],
        salary_to=200000, format='remote'))
    assert need.status_code == 201, need.text
    search = employer.post('/api/v1/company/searches', json=need.json()['query']).json()
    assert candidate_id in search['candidate_ids']
    row = next(r for r in search['rows'] if r['id'] == candidate_id)
    assert row['specialization'] == 'design' and row['confirmed_grade'] == 'junior' and 'contact' not in row
    assert 'contact' not in employer.get('/api/v1/company/candidates/' + candidate_id).json()  # скрыт до решения
    offer = invite(employer, key='live-flow-key-1', candidate=candidate_id,
                   description='Приглашаем в команду продуктового дизайна', salary_from=140000, salary_to=190000)
    assert offer.status_code == 201, offer.text
    employer_id = offer.json()['company_id']
    assert employer.post(f'/api/v1/company/chats/{candidate_id}/messages', json={'body': 'Рано'}).status_code == 404

    # Участник видит условия до общения, принимает предложение; контакт открывается; начинается переписка.
    invitations = client.get('/api/v1/candidate/invitations').json()
    assert invitations and invitations[0]['salary_from'] == 140000 and invitations[0]['currency'] == 'RUB'
    path = f"/api/v1/candidate/invitations/{invitations[0]['id']}/decision"
    assert client.post(path, json={'decision': 'accepted'}).status_code == 200
    assert employer.get('/api/v1/company/candidates/' + candidate_id).json()['contact'] == 'designer-live@example.invalid'
    assert employer.post(f'/api/v1/company/chats/{candidate_id}/messages', json={'body': 'Добро пожаловать'}).status_code == 201
    assert client.get('/api/v1/candidate/chats').json()[0]['unread'] == 1
    assert client.post(f'/api/v1/candidate/chats/{employer_id}/messages', json={'body': 'Спасибо, готов'}).status_code == 201

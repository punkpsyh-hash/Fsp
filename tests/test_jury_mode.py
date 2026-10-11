"""Парольный показ не открывает mock-идентификацию или чужую базу."""
from uuid import uuid4
import os

from fastapi.testclient import TestClient
import pytest

from src.server.app import create_app
from src.server.db import database, database_url
from src.server.models import Base, User
from src.server import jury

TEST_PASSWORD = 'synthetic-jury-password-for-tests'


@pytest.fixture
def jury_env(monkeypatch):
    values = {
        'FSP_JURY_MODE': '1', 'FSP_JURY_PASSWORD': TEST_PASSWORD,
        'FSP_JURY_OPERATOR_NAME': 'Тестовый оператор <script>test</script>',
        # Не отправляется и не публикуется: синтетический тест конфигурации.
        'FSP_JURY_OPERATOR_CONTACT': 'operator@example.org',
        'FSP_JURY_OPERATOR_CONFIRMED': '1',
        'FSP_JURY_STORAGE_COUNTRY': 'RU', 'FSP_COOKIE_SECURE': '1',
        'FSP_SMTP_ENABLED': '0', 'FSP_SMTP_HOST': '',
        'FSP_ALLOWED_HOSTS': 'jury.example.invalid',
        'FSP_ALLOWED_ORIGINS': 'https://jury.example.invalid',
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def jury_client(tmp_path, jury_env):
    admin, schema = None, None
    url = 'sqlite:///' + str(tmp_path / 'jury.sqlite')
    if os.environ.get('FSP_TEST_POSTGRES') == '1':
        schema = 'fsp_test_' + uuid4().hex
        admin, _ = database(database_url())
        with admin.begin() as conn:
            conn.exec_driver_sql('CREATE SCHEMA "' + schema + '"')
        url = database_url().update_query_dict({'options': '-csearch_path=' + schema})
    app = create_app(url, demo=True)
    Base.metadata.create_all(app.state.engine)
    try:
        with TestClient(app, base_url='https://jury.example.invalid') as client:
            yield client
    finally:
        if admin:
            with admin.begin() as conn:
                conn.exec_driver_sql('DROP SCHEMA "' + schema + '" CASCADE')
            admin.dispose()


@pytest.mark.parametrize('path', sorted(jury.BLOCKED_PATHS) + [
    '/api/v1/auth/mock-fsp-id/authorize', '/api/v1/candidate/fsp-id/start',
])
def test_jury_blocks_mock_entry_and_upload_before_reading_body(jury_client, path):
    for method in ('GET', 'POST'):
        response = jury_client.request(method, path + '/', content=b'not-json', headers={'Origin': 'https://jury.example.invalid'})
        assert response.status_code == 404
        assert response.json()['code'] == 'jury_mode'


def test_password_session_csrf_and_logout_work(jury_client):
    assert jury_client.get('/api/health').json()['mode'] == 'jury-demo'
    response = jury_client.post('/api/v1/auth/password-login', json={
        'email': 'demo-candidate-a@example.invalid', 'password': TEST_PASSWORD,
    })
    assert response.status_code == 200
    assert 'Secure' in response.headers['set-cookie']
    assert 'HttpOnly' in response.headers['set-cookie']
    assert jury_client.get('/api/v1/me').status_code == 200
    assert jury_client.post('/api/v1/auth/logout').status_code == 403
    assert jury_client.post('/api/v1/auth/logout', headers={'X-CSRF-Token': response.json()['csrf']}).status_code == 204
    assert jury_client.get('/api/v1/me').status_code == 401


def test_policy_is_available_without_session_and_escapes_operator(jury_client):
    for path in ('/legal/privacy', '/legal/recommendations'):
        response = jury_client.get(path)
        assert response.status_code == 200
        assert '<script>test</script>' not in response.text
        assert '&lt;script&gt;test&lt;/script&gt;' in response.text
        assert 'operator@example.org' in response.text
        assert 'не является политикой неуказанного' not in response.text
    assert 'рекомендательные технологии' in jury_client.get('/legal/recommendations').text
    assert '/legal/privacy' not in jury_client.app.openapi()['paths']


@pytest.mark.parametrize(('key', 'value'), [
    ('FSP_JURY_OPERATOR_NAME', ''), ('FSP_JURY_OPERATOR_CONTACT', ''),
    ('FSP_JURY_OPERATOR_CONTACT', 'contact-without-email'),
    ('FSP_JURY_OPERATOR_CONTACT', 'operator@example.invalid'),
    ('FSP_JURY_PASSWORD', 'short'), ('FSP_JURY_STORAGE_COUNTRY', 'US'),
    ('FSP_JURY_PASSWORD', 'a' * 32), ('FSP_JURY_OPERATOR_CONFIRMED', '0'),
    ('FSP_COOKIE_SECURE', '0'), ('FSP_SMTP_ENABLED', '1'),
    ('FSP_SMTP_HOST', 'smtp.example.invalid'), ('FSP_JURY_MODE', 'yes'),
])
def test_incomplete_jury_configuration_fails_closed(jury_env, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError):
        jury.configuration()


def test_existing_non_seed_database_is_not_converted(jury_client):
    with jury_client.app.state.factory() as db:
        db.add(User(id='unexpected', email='unexpected@example.invalid', role='candidate', label='Synthetic extra', verified=True))
        db.commit()
    with pytest.raises(RuntimeError, match='отдельная база'):
        jury.prepare_accounts(jury_client.app.state.factory, jury.configuration())


def test_password_rotation_invalidates_previous_sessions(jury_client):
    response = jury_client.post('/api/v1/auth/password-login', json={
        'email': 'demo-candidate-a@example.invalid', 'password': TEST_PASSWORD,
    })
    assert response.status_code == 200
    config = jury.configuration()
    config['password'] = TEST_PASSWORD + '-rotated'
    jury.prepare_accounts(jury_client.app.state.factory, config)
    assert jury_client.get('/api/v1/me').status_code == 401

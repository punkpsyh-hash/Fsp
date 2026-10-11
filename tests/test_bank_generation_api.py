"""Права, отсутствие автоматической публикации и ограничения генерации."""
from copy import deepcopy

import pytest

from tests.test_api import client, login
from tests.test_banks import create_bank, publish
from src.server import banks, llm
from src.server.bank_generation import GenerationUnavailable, GenerationRejected
from src.server.bank_models import BankVersion


def endpoint(bank):
    version = bank['current_version']
    return f"/api/v1/company/banks/{bank['id']}/versions/{version['id']}/suggest-task"


def request(bank):
    version = bank['current_version']
    return {'revision': version['revision'], 'kind': 'single_choice',
            'specialization': version['specialization'], 'grade': version['grade'],
            'skills': ['python'], 'brief': 'Задача про обработку повторных событий в очереди'}


def test_suggestion_is_private_and_does_not_save_or_publish(client):
    bank = create_bank(client)
    path, body = endpoint(bank), request(bank)
    assert client.post(path, json=body).status_code == 503
    client.app.state.llm = llm.LLMConfig('mock')
    before = deepcopy(client.get('/api/v1/company/banks/' + bank['id']).json())
    result = client.post(path, json=body)
    assert result.status_code == 200, result.text
    suggestion = result.json()
    assert suggestion['source'] == 'llm-mock' and suggestion['review_required'] is True
    assert suggestion['task']['answer_key']
    assert client.get('/api/v1/company/banks/' + bank['id']).json() == before
    login(client, 'employer-y')
    assert client.post(path, json=body).status_code == 404
    login(client, 'candidate-a')
    assert client.post(path, json=body).status_code == 403


def test_suggestion_requires_current_owned_draft_and_supported_type(client):
    bank = create_bank(client)
    client.app.state.llm = llm.LLMConfig('mock')
    path, body = endpoint(bank), request(bank)
    assert client.post(path, json={**body, 'revision': 99}).status_code == 409
    assert client.post(path, json={**body, 'grade': 'middle'}).status_code == 409
    assert client.post(path, json={**body, 'kind': 'code'}).status_code == 422
    assert client.post(path, json={**body, 'skills': []}).status_code == 422
    publish(client, bank)
    assert client.post(path, json=body).status_code == 409


@pytest.mark.parametrize('failure,status', [(GenerationUnavailable, 503), (GenerationRejected, 502)])
def test_failed_generation_does_not_change_version_or_leak_provider_text(client, monkeypatch, failure, status):
    bank = create_bank(client)
    client.app.state.llm = llm.LLMConfig('mock')
    def fail(*args):
        raise failure('private upstream text must never be returned')
    monkeypatch.setattr(banks, 'generate_task', fail)
    response = client.post(endpoint(bank), json=request(bank))
    assert response.status_code == status
    assert 'private upstream' not in response.text
    current = client.get('/api/v1/company/banks/' + bank['id']).json()['current_version']
    assert current == bank['current_version']


def test_generation_has_per_author_rate_limit(client):
    bank = create_bank(client)
    client.app.state.llm = llm.LLMConfig('mock')
    for _ in range(10):
        assert client.post(endpoint(bank), json=request(bank)).status_code == 200
    response = client.post(endpoint(bank), json=request(bank))
    assert response.status_code == 429 and response.headers['retry-after'] == '60'


def test_concurrent_edit_discards_suggestion(client, monkeypatch):
    bank = create_bank(client)
    client.app.state.llm = llm.LLMConfig('mock')
    original = banks.generate_task
    def edit_during_generation(*args):
        suggestion = original(*args)
        with client.app.state.factory() as db:
            version = db.get(BankVersion, bank['current_version']['id'])
            version.revision += 1
            db.commit()
        return suggestion
    monkeypatch.setattr(banks, 'generate_task', edit_during_generation)
    response = client.post(endpoint(bank), json=request(bank))
    assert response.status_code == 409
    current = client.get('/api/v1/company/banks/' + bank['id']).json()['current_version']
    assert current['revision'] == bank['current_version']['revision'] + 1
    assert current['tasks'] == bank['current_version']['tasks']

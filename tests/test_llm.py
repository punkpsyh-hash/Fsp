"""ИИ-помощник: выключен по умолчанию, белый список фактов, проверка ответа, откат на шаблон."""
import json

import pytest
import httpx

from src.server import llm
from tests.test_api import client, login  # noqa: F401  (fixture)

ROW = {
    'id': 'candidate-a', 'alias': 'P-104', 'specialization': 'backend', 'confirmed_grade': 'junior', 'test_score': 91.67,
    'score': 71.3, 'matched': ['python', 'sql'], 'missing': ['http'],
    'components': {'assessment': 41.25, 'skills': 23.333, 'fsp': 0, 'freshness': 6.7},
    'fsp_state': 'none', 'integrity_level': 'clean', 'work_matches': [],
    'contact': 'secret@example.invalid', 'experience': {'roles': ['Иван Петров']}, 'resume': 'приватный текст',
}


class Fixed:
    model = 'fixed-test-model'

    def __init__(self, text=None, error=None):
        self.text, self.error, self.prompts = text, error, []

    def complete(self, system, user, max_tokens=220, temperature=0.2):
        self.prompts.append((system, user))
        if self.error:
            raise self.error
        return self.text


MOCK = llm.LLMConfig('mock')


def test_disabled_by_default_and_uses_template(monkeypatch):
    monkeypatch.delenv('FSP_LLM_PROVIDER', raising=False)
    config = llm.config_from_env()
    assert not config.enabled
    result = llm.explain(ROW, config)
    assert result['source'] == 'template' and result['model'] is None
    assert 'Backend' in result['text'] and 'python, sql' in result['text'] and 'http' in result['text']


def test_prompt_contains_only_allow_listed_facts():
    provider = Fixed('Backend Junior, тест 91,67 из 100; совпали навыки: python, sql. Итоговый балл 71,3.')
    llm.explain(ROW, MOCK, provider)
    payload = provider.prompts[0][1]
    for private in ('secret@example.invalid', 'Иван Петров', 'приватный текст', 'P-104', 'candidate-a'):
        assert private not in payload
    assert json.loads(payload)['matched_skills'] == ['python', 'sql']


def test_valid_model_answer_is_used():
    text = 'Backend Junior, тест 91,67 из 100; совпали навыки: python, sql. Итоговый балл 71,3.'
    result = llm.explain(ROW, MOCK, Fixed(text))
    assert result == {'text': text, 'source': 'llm-mock', 'model': 'fixed-test-model', 'fallback_reason': None}


@pytest.mark.parametrize('answer,reason', [
    ('Кандидат набрал 99 баллов из 100 и подходит отлично.', 'numbers'),
    ('Знает python, sql и javascript на высоком уровне, тест 91,67.', 'skills'),
    ('Ок', 'length'),
])
def test_invented_numbers_skills_or_short_answers_fall_back(answer, reason):
    result = llm.explain(ROW, MOCK, Fixed(answer))
    assert result['source'] == 'template' and result['fallback_reason'] == 'rejected:' + reason


def test_provider_failure_never_breaks_explanation():
    result = llm.explain(ROW, MOCK, Fixed(error=TimeoutError('slow')))
    assert result['source'] == 'template' and result['fallback_reason'] == 'unavailable:TimeoutError'


def test_structured_provider_sends_schema_and_rejects_truncated_output(monkeypatch):
    sent = []
    finish = {'reason': 'stop'}

    def fake_post(url, **kwargs):
        sent.append((url, kwargs))
        return httpx.Response(200, request=httpx.Request('POST', url), json={'choices': [{
            'finish_reason': finish['reason'], 'message': {'content': '{"id":"suggestion"}'}}]})

    monkeypatch.setattr(llm.httpx, 'post', fake_post)
    provider = llm.OpenAICompatible(llm.LLMConfig(
        'openai-compatible', 'http://localhost:8001/v1', 'local-model', 'private-key', 60))
    schema = {'type': 'object', 'properties': {'id': {'type': 'string'}}}
    assert provider.complete_structured('system', 'user', schema) == '{"id":"suggestion"}'
    url, call = sent[0]
    assert url == 'http://localhost:8001/v1/chat/completions'
    assert call['headers'] == {'Authorization': 'Bearer private-key'}
    assert call['json']['response_format']['json_schema']['schema'] == schema
    assert call['json']['max_tokens'] == 768
    finish['reason'] = 'length'
    with pytest.raises(ValueError):
        provider.complete_structured('system', 'user', schema)
    # Объяснения по-прежнему используют старый путь без response_format.
    assert provider.complete('system', 'user') == '{"id":"suggestion"}'
    assert 'response_format' not in sent[-1][1]['json']


@pytest.mark.parametrize('url,ok', [
    ('https://llm.example.invalid/v1', True), ('http://localhost:11434/v1', True),
    ('http://192.168.1.5:8000/v1', True), ('http://ollama:11434/v1', True),
    ('http://llm.example.invalid/v1', False), ('ftp://x/v1', False), ('', False),
])
def test_endpoint_policy(url, ok):
    env = {'FSP_LLM_PROVIDER': 'openai-compatible', 'FSP_LLM_BASE_URL': url, 'FSP_LLM_MODEL': 'm'}
    if ok:
        assert llm.config_from_env(env).enabled
    else:
        with pytest.raises(ValueError):
            llm.config_from_env(env)


def test_unknown_provider_and_missing_model_are_rejected():
    with pytest.raises(ValueError):
        llm.config_from_env({'FSP_LLM_PROVIDER': 'cloud'})
    with pytest.raises(ValueError):
        llm.config_from_env({'FSP_LLM_PROVIDER': 'openai-compatible', 'FSP_LLM_BASE_URL': 'https://a.example.invalid/v1'})


def test_redact_removes_contacts():
    text = 'Пишите на ivan@example.com или +7 (999) 123-45-67, профиль https://x.example/y, паспорт 4510123456'
    cleaned = llm.redact(text)
    for fragment in ('ivan@example.com', '999', 'https://', '4510123456'):
        assert fragment not in cleaned


def test_explanation_endpoint_ownership_and_audit(client):
    login(client, 'employer-x')
    search = client.post('/api/v1/company/searches', json={'specialization': 'backend', 'grade': 'junior'}).json()
    assert search['rows']
    row = search['rows'][0]
    path = f"/api/v1/company/searches/{search['id']}/candidates/{row['id']}/explanation"
    result = client.post(path)
    assert result.status_code == 200 and result.json()['source'] == 'template'
    client.app.state.llm = MOCK
    assert client.post(path).json()['source'] == 'llm-mock'
    assert client.post(f"/api/v1/company/searches/{search['id']}/candidates/nobody/explanation").status_code == 404
    login(client, 'employer-y')
    assert client.post(path).status_code == 404
    login(client, 'candidate-a')
    assert client.post(path).status_code == 403


def test_generation_uses_its_own_longer_timeout(monkeypatch):
    seen = []

    def fake_post(url, headers=None, timeout=None, json=None):
        seen.append((json.get('response_format') is not None, timeout))
        return httpx.Response(200, request=httpx.Request('POST', url), json={'choices': [{
            'finish_reason': 'stop', 'message': {'content': '{}'}}]})

    monkeypatch.setattr(llm.httpx, 'post', fake_post)
    provider = llm.OpenAICompatible(llm.config_from_env({
        'FSP_LLM_PROVIDER': 'openai-compatible', 'FSP_LLM_BASE_URL': 'http://localhost:8001/v1',
        'FSP_LLM_MODEL': 'm', 'FSP_LLM_TIMEOUT': '8', 'FSP_LLM_GENERATION_TIMEOUT': '90'}))
    provider.complete('s', 'u')
    provider.complete_structured('s', 'u', {'type': 'object'})
    assert seen == [(False, 8.0), (True, 90.0)]
    with pytest.raises(ValueError):
        llm.config_from_env({'FSP_LLM_PROVIDER': 'none', 'FSP_LLM_GENERATION_TIMEOUT': '500'})


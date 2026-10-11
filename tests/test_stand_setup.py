"""Ready-check не подменяет готовность модели доступностью обычного API."""
import httpx
import pytest

from ml.local_model import ChatRequest
from scripts import check_stand
from src.server.llm import LLMConfig


def setup_check(monkeypatch, provider='openai-compatible', accepted=True, ready=True):
    config = LLMConfig(provider, 'http://model:8001/v1', 'Qwen/Qwen3-4B-Instruct-2507', 'synthetic-key', 100, 120)
    monkeypatch.setattr(check_stand, 'config_from_env', lambda: config)
    original_client = httpx.Client

    def handle(request):
        if request.url.path == '/api/health':
            return httpx.Response(200, json={'status': 'ok'})
        if request.url.path == '/health':
            return httpx.Response(200, json={
                'status': 'ready' if ready else 'loading', 'model': config.model,
                'revision': 'cdbee75f17c01a7cc42f958dc650907174af0554',
                'quantization': {'type': 'nf4', 'placement': 'cuda:0'}})
        # Проверяем реальную входную модель сервиса: запрос должен дойти до auth.
        ChatRequest.model_validate_json(request.content)
        return httpx.Response(422 if accepted else 401, json={
            'detail': {'code': 'input_rejected'} if accepted else 'Требуется ключ'})

    monkeypatch.setattr(check_stand.httpx, 'Client', lambda **kwargs: original_client(
        transport=httpx.MockTransport(handle), **kwargs))


def test_local_check_requires_model_even_if_base_api_is_ready(monkeypatch):
    setup_check(monkeypatch, provider='none')
    assert check_stand.check()['api_and_database'] == 'ready'
    with pytest.raises(ValueError, match='без локальной'):
        check_stand.check(require_local_llm=True)


@pytest.mark.parametrize('accepted,ready', [(False, True), (True, False)])
def test_local_check_rejects_wrong_key_or_unready_model(monkeypatch, accepted, ready):
    setup_check(monkeypatch, accepted=accepted, ready=ready)
    with pytest.raises(ValueError):
        check_stand.check(require_local_llm=True)


def test_local_check_accepts_pinned_ready_model_with_verified_auth(monkeypatch):
    setup_check(monkeypatch)
    assert check_stand.check(require_local_llm=True)['local_model'] == 'ready'

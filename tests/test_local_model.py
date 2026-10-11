"""Контракт и границы локального сервиса без загрузки GPU или весов."""
import asyncio
from hashlib import sha256
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
import yaml

from ml import local_model
from src.server.bank_generation import task_generation_schema as task_json_schema


ROOT = Path(__file__).resolve().parents[1]


def test_manifest_requires_pinned_revision_exact_file_set_and_hashes(tmp_path):
    assert local_model.MODEL_ID == 'Qwen/Qwen3-4B-Instruct-2507'
    assert local_model.MODEL_REVISION == 'cdbee75f17c01a7cc42f958dc650907174af0554'
    folder = tmp_path / 'model'
    folder.mkdir()
    for name in ('config.json', 'tokenizer.json', 'model.safetensors'):
        (folder / name).write_bytes(name.encode())
    manifest = {'model_id': local_model.MODEL_ID, 'revision': local_model.MODEL_REVISION,
                'files': {p.name: sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}}
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    assert local_model.verify_manifest(folder, path)['revision'] == local_model.MODEL_REVISION
    wrong_revision = dict(manifest, revision='0' * 40)
    path.write_text(json.dumps(wrong_revision), encoding='utf-8')
    with pytest.raises(ValueError, match='commit'):
        local_model.verify_manifest(folder, path)
    path.write_text(json.dumps(manifest), encoding='utf-8')
    (folder / 'model.safetensors').write_bytes(b'changed')
    with pytest.raises(ValueError, match='SHA-256'):
        local_model.verify_manifest(folder, path)
    (folder / 'model.safetensors').write_bytes(b'model.safetensors')
    (folder / 'extra').write_text('unexpected')
    with pytest.raises(ValueError, match='Список файлов'):
        local_model.verify_manifest(folder, path)


def test_quantized_model_must_reside_entirely_on_first_cuda_device():
    class Model:
        is_loaded_in_4bit = True
        hf_device_map = {'': 0}
        parameter_device = 'cuda'
        parameter_index = 0

        def parameters(self):
            yield type('Parameter', (), {'device': type('Device', (), {
                'type': self.parameter_device, 'index': self.parameter_index})()})()

    model = Model()
    local_model.verify_cuda_placement(model)
    model.hf_device_map = {'transformer': 0, 'lm_head': 'cpu'}
    with pytest.raises(RuntimeError, match='CUDA:0'):
        local_model.verify_cuda_placement(model)
    model.hf_device_map = {'': 0}
    model.parameter_device = 'cpu'
    with pytest.raises(RuntimeError, match='Параметры'):
        local_model.verify_cuda_placement(model)
    model.parameter_device = 'cuda'
    model.is_loaded_in_4bit = False
    with pytest.raises(RuntimeError, match='4-битном'):
        local_model.verify_cuda_placement(model)


def test_only_author_task_schemas_accepted():
    schema = task_json_schema('numeric', ['http'])
    assert local_model.checked_schema(schema) == schema
    altered = json.loads(json.dumps(schema))
    altered['properties']['code'] = {'type': 'string'}
    with pytest.raises(ValueError):
        local_model.checked_schema(altered)
    altered = json.loads(json.dumps(schema))
    altered['properties']['type']['enum'] = ['code']
    with pytest.raises(ValueError):
        local_model.checked_schema(altered)


def test_service_auth_schema_busy_and_no_model_text_in_errors(monkeypatch):
    class FakeRuntime:
        manifest = {'revision': local_model.MODEL_REVISION}
        calls = []

        def complete(self, messages, schema, max_tokens):
            self.calls.append((messages, schema, max_tokens))
            return json.dumps({'id': 'suggestion', 'type': 'open_response',
                               'title': 'Проверка HTTP',
                               'prompt': 'Опишите проверку успешного HTTP-ответа и ошибочного запроса.',
                               'skills': ['http'],
                               'solution': 'Нужно описать успешный запрос и ошибочный запрос с ожидаемыми кодами.',
                               'rubric': '0: ответ отсутствует. 50: назван один проверяемый сценарий. '
                                         '100: описаны обычный и ошибочный запросы с ожидаемыми результатами.'})

    fake = FakeRuntime()
    monkeypatch.setattr(local_model, 'runtime', fake)
    monkeypatch.setenv('FSP_LOCAL_MODEL_API_KEY', 'secret-for-test')
    body = {'model': local_model.MODEL_ID,
            'messages': [{'role': 'system', 'content': 'System'},
                         {'role': 'user', 'content': 'Private brief'}],
            'max_tokens': 768, 'temperature': 0.2,
            'response_format': {'type': 'json_schema', 'json_schema': {
                'name': 'task_draft', 'strict': True,
                'schema': task_json_schema('open_response', ['http'])}}}
    client = TestClient(local_model.app)
    assert client.get('/health').json()['status'] == 'ready'
    assert client.post('/v1/chat/completions', json=body).status_code == 401
    headers = {'Authorization': 'Bearer secret-for-test'}
    response = client.post('/v1/chat/completions', json=body, headers=headers)
    assert response.status_code == 200
    assert response.json()['choices'][0]['finish_reason'] == 'stop'
    assert len(fake.calls) == 1
    assert 'Private brief' not in response.text
    assert response.json()['choices'][0]['message']['content']
    bad = json.loads(json.dumps(body))
    bad['response_format']['json_schema']['schema']['additionalProperties'] = True
    assert client.post('/v1/chat/completions', json=bad, headers=headers).status_code == 422
    assert local_model.active_request.acquire(blocking=False)
    try:
        assert client.post('/v1/chat/completions', json=body, headers=headers).status_code == 429
    finally:
        local_model.active_request.release()


@pytest.mark.parametrize(('failure', 'status', 'code'), [
    (local_model.LocalSchemaRejected('private-output'), 502, 'schema_rejected'),
    (local_model.GenerationIncomplete('private-output'), 502, 'generation_incomplete'),
    (ValueError('private-context'), 422, 'input_rejected'),
    (RuntimeError('private-runtime'), 502, 'runtime_unavailable'),
])
def test_service_returns_stable_private_machine_error_codes(monkeypatch, failure, status, code):
    class BrokenRuntime:
        manifest = {'revision': local_model.MODEL_REVISION}

        def complete(self, messages, schema, max_tokens):
            raise failure

    monkeypatch.setattr(local_model, 'runtime', BrokenRuntime())
    monkeypatch.delenv('FSP_LOCAL_MODEL_API_KEY', raising=False)
    body = {'model': local_model.MODEL_ID,
            'messages': [{'role': 'system', 'content': 'System'},
                         {'role': 'user', 'content': 'Private brief'}],
            'max_tokens': 768, 'temperature': 0.2,
            'response_format': {'type': 'json_schema', 'json_schema': {
                'name': 'task_draft', 'strict': True,
                'schema': task_json_schema('open_response', ['http'])}}}
    response = TestClient(local_model.app).post('/v1/chat/completions', json=body)
    assert response.status_code == status
    assert response.json() == {'detail': {'code': code}}
    assert 'private-' not in response.text


def test_request_rejects_large_or_incomplete_contract():
    base = {'model': local_model.MODEL_ID, 'messages': [
        {'role': 'system', 'content': 'a'}, {'role': 'user', 'content': 'b'}],
        'max_tokens': local_model.MAX_OUTPUT_TOKENS + 1, 'temperature': 0.2,
        'response_format': {'type': 'json_schema', 'json_schema': {
            'name': 'task_draft', 'strict': True,
            'schema': task_json_schema('single_choice', ['http'])}}}
    with pytest.raises(Exception):
        local_model.ChatRequest.model_validate(base)
    base['max_tokens'] = local_model.MAX_OUTPUT_TOKENS
    base['messages'].reverse()
    with pytest.raises(Exception):
        local_model.ChatRequest.model_validate(base)


def test_body_limit_runs_before_json_parse_without_content_length():
    called = False

    async def inner(scope, receive, send):
        nonlocal called
        called = True

    middleware = local_model.BodyLimitMiddleware(inner)
    chunks = iter([{'type': 'http.request', 'body': b'x' * 9000, 'more_body': True},
                   {'type': 'http.request', 'body': b'x' * 9000, 'more_body': False}])
    output = []

    async def receive():
        return next(chunks)

    async def send(message):
        output.append(message)

    scope = {'type': 'http', 'method': 'POST', 'path': '/v1/chat/completions', 'headers': []}
    asyncio.run(middleware(scope, receive, send))
    assert not called
    assert output[0]['status'] == 413


def test_startup_failure_report_is_private_and_replaced_atomically(tmp_path, monkeypatch):
    report_path = tmp_path / 'startup.json'
    monkeypatch.setenv('FSP_LOCAL_MODEL_STARTUP_REPORT', str(report_path))
    monkeypatch.setenv('FSP_LOCAL_MODEL_PATH', str(tmp_path / 'model'))
    monkeypatch.setenv('FSP_LOCAL_MODEL_MANIFEST', str(tmp_path / 'manifest.json'))

    def failed_runtime(*args):
        raise RuntimeError('private-model-text secret-token private-path')

    monkeypatch.setattr(local_model, 'LocalRuntime', failed_runtime)
    with pytest.raises(RuntimeError):
        with TestClient(local_model.app):
            pass
    report = json.loads(report_path.read_text())
    assert report == {'status': 'error', 'model': local_model.MODEL_ID,
                      'revision': local_model.MODEL_REVISION, 'error_type': 'RuntimeError'}
    assert local_model.runtime is None
    local_model._write_startup_report({'status': 'ready'})
    assert json.loads(report_path.read_bytes()) == {'status': 'ready'}
    assert not list(tmp_path.glob('.startup-*.tmp'))
    previous = report_path.read_bytes()

    def fail_replace(*args):
        raise OSError('simulated filesystem failure')

    monkeypatch.setattr(local_model.os, 'replace', fail_replace)
    with pytest.raises(OSError):
        local_model._write_startup_report({'status': 'error', 'error_type': 'ValueError'})
    assert report_path.read_bytes() == previous
    assert not list(tmp_path.glob('.startup-*.tmp'))


def test_warmup_failure_prevents_readiness(tmp_path, monkeypatch):
    report_path = tmp_path / 'startup.json'
    monkeypatch.setenv('FSP_LOCAL_MODEL_STARTUP_REPORT', str(report_path))
    monkeypatch.setenv('FSP_LOCAL_MODEL_PATH', str(tmp_path / 'model'))
    monkeypatch.setenv('FSP_LOCAL_MODEL_MANIFEST', str(tmp_path / 'manifest.json'))
    monkeypatch.setenv('FSP_LOCAL_MODEL_WARMUP', '1')
    monkeypatch.delenv('FSP_LOCAL_ADAPTER_PATH', raising=False)
    monkeypatch.delenv('FSP_LOCAL_ADAPTER_MANIFEST', raising=False)

    class RuntimeWithFailedWarmup:
        manifest = {'revision': local_model.MODEL_REVISION}
        adapter = None

        def __init__(self, *args):
            pass

        def warmup(self):
            raise local_model.GenerationIncomplete('private warmup output')

    monkeypatch.setattr(local_model, 'LocalRuntime', RuntimeWithFailedWarmup)
    with pytest.raises(local_model.GenerationIncomplete):
        with TestClient(local_model.app):
            pass
    assert local_model.runtime is None
    assert json.loads(report_path.read_text()) == {
        'status': 'error', 'model': local_model.MODEL_ID,
        'revision': local_model.MODEL_REVISION, 'error_type': 'GenerationIncomplete'}
    assert 'private' not in report_path.read_text()


def test_warmup_requires_exact_minimum_schema_result():
    class StubRuntime:
        def __init__(self, result):
            self.result = result
            self.calls = []

        def complete(self, messages, schema, max_tokens):
            self.calls.append((messages, schema, max_tokens))
            return self.result

    runtime = StubRuntime('{"status": "ready"}')
    local_model.LocalRuntime.warmup(runtime)
    assert runtime.calls[0][1:] == (local_model.WARMUP_SCHEMA, 24)
    with pytest.raises(local_model.LocalSchemaRejected):
        local_model.LocalRuntime.warmup(StubRuntime('{"status": "failed"}'))


def test_llm_compose_wires_model_readiness_warmup_and_pinned_base_image():
    compose = yaml.safe_load((ROOT / 'compose.llm.yaml').read_text(encoding='utf-8'))
    assert compose['services']['model']['environment']['FSP_LOCAL_MODEL_WARMUP'] == '${FSP_LOCAL_MODEL_WARMUP:-1}'
    assert compose['services']['app']['depends_on']['model'] == {'condition': 'service_healthy'}
    assert 'fsp-model-diagnostics:/diagnostics' in compose['services']['model']['volumes']
    assert compose['services']['model']['restart'] == 'no'
    dockerfile = (ROOT / 'docker' / 'model.Dockerfile').read_text(encoding='utf-8')
    assert 'python:3.12-slim@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e' in dockerfile


def test_adapter_must_match_pinned_base_and_hashes(tmp_path):
    folder = tmp_path / 'adapter'
    folder.mkdir()
    for name in ('adapter_config.json', 'adapter_model.safetensors'):
        (folder / name).write_bytes(name.encode())
    manifest = {'adapter_id': 'test', 'base_model_id': local_model.MODEL_ID,
                'base_revision': local_model.MODEL_REVISION,
                'files': {p.name: sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}}
    path = tmp_path / 'adapter-manifest.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    assert local_model.verify_adapter(folder, path)['adapter_id'] == 'test'
    path.write_text(json.dumps(dict(manifest, base_revision='0' * 40)), encoding='utf-8')
    with pytest.raises(ValueError, match='закреплённой'):
        local_model.verify_adapter(folder, path)
    path.write_text(json.dumps(manifest), encoding='utf-8')
    (folder / 'adapter_model.safetensors').write_bytes(b'changed')
    with pytest.raises(ValueError, match='SHA-256'):
        local_model.verify_adapter(folder, path)

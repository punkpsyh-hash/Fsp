"""Проверки происхождения оценки без загрузки весов и доступа к закрытым кейсам."""
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from ml import evaluate_local_model as evaluation
from ml.local_model import MODEL_ID, MODEL_REVISION
from src.server.llm import LLMConfig


def test_manifest_requires_exact_served_model_and_revision(tmp_path):
    path = tmp_path / 'manifest.json'
    manifest = {'model_id': MODEL_ID, 'revision': MODEL_REVISION, 'files': {}}
    path.write_text(json.dumps(manifest), encoding='utf-8')
    assert evaluation.manifest_info(path, MODEL_ID)['revision'] == MODEL_REVISION

    with pytest.raises(ValueError, match='FSP_LLM_MODEL'):
        evaluation.manifest_info(path, 'Qwen/another-model')
    manifest['model_id'] = 'Qwen/another-model'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='закреплённой модели'):
        evaluation.manifest_info(path, MODEL_ID)
    manifest['model_id'] = MODEL_ID
    manifest['revision'] = '0' * 40
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='commit'):
        evaluation.manifest_info(path, MODEL_ID)


def test_prepare_freezes_publication_schema_and_serving_dependencies(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, 'ROOT', tmp_path)
    runs = tmp_path / 'ml' / 'runs'
    runs.mkdir(parents=True)
    monkeypatch.setattr(evaluation, 'RUNS', runs)
    assert {'src/server/bank_schemas.py', 'src/server/schemas.py',
            'ml/requirements-local-model.txt', 'scripts/run-local-model.ps1'} <= set(evaluation.CODE_FILES)
    for name in evaluation.CODE_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode('utf-8'))

    cases = tmp_path / 'cases.json'
    cases.write_text(json.dumps({'cases': [{
        'id': 'case-1', 'family': 'family-1', 'kind': 'numeric',
        'specialization': 'backend', 'grade': 'junior', 'skills': ['http'],
        'brief': 'Составьте задание про измерение задержки HTTP-запроса.'
    }]}), encoding='utf-8')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'model_id': MODEL_ID, 'revision': MODEL_REVISION,
                                    'files': {}}), encoding='utf-8')
    config = LLMConfig('openai-compatible', 'http://localhost:8001/v1', MODEL_ID, '', 2.0)
    monkeypatch.setattr(evaluation.llm, 'config_from_env', lambda: config)
    monkeypatch.setattr(evaluation.httpx, 'get', lambda *_args, **_kwargs: SimpleNamespace(
        json=lambda: {'status': 'ready', 'model': MODEL_ID, 'revision': MODEL_REVISION}))

    _, output, _, frozen = evaluation.prepare(SimpleNamespace(
        cases=str(cases), out_dir=str(runs / 'new'), model_manifest=str(manifest)))
    assert output == runs / 'new'
    assert set(frozen['code_sha256']) == set(evaluation.CODE_FILES)
    schema_path = tmp_path / 'src/server/bank_schemas.py'
    expected = sha256('src/server/bank_schemas.py'.encode()).hexdigest()
    assert frozen['code_sha256']['src/server/bank_schemas.py'] == expected
    schema_path.write_text('changed', encoding='utf-8')
    assert not evaluation.unchanged(schema_path, expected)

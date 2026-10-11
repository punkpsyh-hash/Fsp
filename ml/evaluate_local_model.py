"""Однократная оценка локальной генерации на закрытом наборе авторских запросов.

Сохраняет входной хеш и хеши кода после health-проверки, до запросов генерации. Полные ответы
модели остаются в игнорируемом Git каталоге ml/runs; stdout не содержит brief.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import time

import httpx

from pydantic import ValidationError

from src.server import llm
from src.server.bank_generation import (
    GenerationRejected, GenerationRequest, GenerationUnavailable, _local_endpoint, generate_task,
)
from ml.local_model import MODEL_ID, MODEL_REVISION


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'ml' / 'runs'
CODE_FILES = (
    'src/server/bank_generation.py', 'src/server/bank_schemas.py',
    'src/server/schemas.py', 'src/server/llm.py',
    'ml/local_model.py', 'ml/requirements-local-model.txt',
    'scripts/run-local-model.ps1', 'ml/evaluate_local_model.py',
)
KINDS = ('single_choice', 'multiple_choice', 'numeric', 'open_response')
MAX_CASES = 24


def digest(path: Path) -> str:
    hash_value = sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            hash_value.update(chunk)
    return hash_value.hexdigest()


def unchanged(path: Path, expected: str) -> bool:
    try:
        return digest(path) == expected
    except OSError:
        return False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_cases(path: Path) -> list[dict]:
    document = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(document, dict) or not isinstance(document.get('cases'), list):
        raise ValueError('Ожидается JSON-объект с массивом cases')
    values = document['cases']
    if not 1 <= len(values) <= MAX_CASES:
        raise ValueError(f'Нужно от 1 до {MAX_CASES} запросов')
    seen = set()
    cases = []
    required = {'id', 'family', 'kind', 'specialization', 'grade', 'skills', 'brief'}
    for value in values:
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError('Каждый case должен содержать только id, family и поля GenerationRequest')
        case_id, family = value['id'], value['family']
        if any(not isinstance(item, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', item)
               for item in (case_id, family)):
            raise ValueError('id и family должны быть безопасными короткими идентификаторами')
        if case_id in seen:
            raise ValueError('Повторяется id запроса')
        seen.add(case_id)
        request = GenerationRequest.model_validate({key: value[key] for key in required - {'id', 'family'}})
        cases.append({'id': case_id, 'family': family, 'request': request})
    return cases


def manifest_info(path: Path, model: str) -> dict:
    if model != MODEL_ID:
        raise ValueError('FSP_LLM_MODEL не соответствует закреплённой модели')
    raw = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(raw, dict) or raw.get('model_id') != MODEL_ID:
        raise ValueError('Manifest модели не соответствует закреплённой модели')
    if raw.get('revision') != MODEL_REVISION:
        raise ValueError('Manifest должен указывать закреплённый commit модели')
    return {'path': str(path), 'sha256': digest(path), 'revision': raw['revision']}


class CapturingProvider:
    """Перехватывает сырой ответ без дополнительного запроса к модели."""
    def __init__(self, inner):
        self.inner = inner
        self.model = inner.model
        self.raw_output = None

    def complete_structured(self, system, user, schema, max_tokens=768, temperature=0.2):
        self.raw_output = self.inner.complete_structured(
            system, user, schema, max_tokens=max_tokens, temperature=temperature)
        return self.raw_output


def prepare(args):
    cases_path = Path(args.cases).resolve(strict=True)
    cases = load_cases(cases_path)
    output = Path(args.out_dir).resolve()
    runs = RUNS.resolve(strict=True)
    if output.parent != runs or output.exists():
        raise ValueError('out-dir должен быть новым непосредственным подкаталогом ml/runs')
    config = llm.config_from_env()
    if config.provider != 'openai-compatible' or not _local_endpoint(config.base_url):
        raise ValueError('Оценка допускает только настроенную локальную openai-compatible модель')
    if not 0 < config.timeout <= 120:
        raise ValueError('FSP_LLM_TIMEOUT должен быть больше 0 и не больше 120 секунд')
    manifest_path = Path(args.model_manifest).resolve(strict=True)
    model_manifest = manifest_info(manifest_path, config.model)
    health = httpx.get(config.base_url.rstrip('/').removesuffix('/v1') + '/health',
                      timeout=min(config.timeout, 10)).json()
    if health.get('status') != 'ready' or health.get('model') != config.model or health.get('revision') != model_manifest['revision']:
        raise ValueError('Загруженная модель не совпадает с закреплённой моделью')
    code_hashes = {name: digest(ROOT / name) for name in CODE_FILES}
    frozen = {
        'created_utc': utc_now(),
        'cases_path': str(cases_path), 'cases_sha256': digest(cases_path),
        'case_count': len(cases), 'code_sha256': code_hashes,
        'model': config.model, 'model_manifest': model_manifest,
        'server_health': health,
        'timeout_seconds': config.timeout, 'retry_count': 0,
        'review_status': 'machine_structure_only_not_semantic_validation',
    }
    output.mkdir(exist_ok=False)
    freeze_path = output / 'frozen.json'
    with freeze_path.open('x', encoding='utf-8') as target:
        json.dump(frozen, target, ensure_ascii=False, indent=2)
        target.write('\n')
    return cases, output, config, frozen


def evaluate(args):
    cases, output, config, frozen = prepare(args)
    started = time.perf_counter()
    provider = CapturingProvider(llm.provider_for(config))
    counts = Counter()
    passed_kinds = Counter()
    records = output / 'case-results.jsonl'
    with records.open('x', encoding='utf-8') as target:
        for case in cases:
            provider.raw_output = None
            began = time.perf_counter()
            record = {'id': case['id'], 'family': case['family'],
                      'kind': case['request'].kind, 'started_utc': utc_now()}
            try:
                result = generate_task(case['request'], config, provider)
                if result.source != 'llm' or not isinstance(provider.raw_output, str):
                    raise GenerationRejected('Ответ локальной модели отсутствует')
                record.update({'passed': True, 'result': result.model_dump(mode='json'),
                               'raw_model_output': provider.raw_output})
                counts['passed'] += 1
                passed_kinds[case['request'].kind] += 1
            except GenerationRejected:
                record.update({'passed': False, 'rejection_type': 'schema_or_publication_rejected'})
            except GenerationUnavailable:
                record.update({'passed': False, 'rejection_type': 'model_or_service_unavailable'})
            except (ValidationError, ValueError):
                record.update({'passed': False, 'rejection_type': 'invalid_case_or_response'})
            except Exception:
                # Исключения могут содержать URL или входной текст; в отчёт они не попадают.
                record.update({'passed': False, 'rejection_type': 'unexpected_error'})
            record['elapsed_seconds'] = round(time.perf_counter() - began, 3)
            record['finished_utc'] = utc_now()
            target.write(json.dumps(record, ensure_ascii=False) + '\n')
            target.flush()
            counts['total'] += 1
    total = counts['total']
    family_kinds = {}
    for case in cases:
        family_kinds.setdefault(case['family'], []).append(case['request'].kind)
    family_matrix = len(family_kinds) == 3 and all(
        len(kinds) == 4 and set(kinds) == set(KINDS) for kinds in family_kinds.values())
    per_kind = {kind: {
        'total': sum(case['request'].kind == kind for case in cases),
        'passed': passed_kinds[kind],
    } for kind in KINDS}
    code_unchanged = all(unchanged(ROOT / name, hash_value)
                         for name, hash_value in frozen['code_sha256'].items())
    cases_unchanged = unchanged(Path(frozen['cases_path']), frozen['cases_sha256'])
    manifest = frozen['model_manifest']
    manifest_unchanged = unchanged(Path(manifest['path']), manifest['sha256'])
    gate = (total == 12 and counts['passed'] >= 11 and family_matrix and
            code_unchanged and cases_unchanged and manifest_unchanged and
            all(per_kind[kind]['total'] >= 1 and per_kind[kind]['passed'] >= 1 for kind in KINDS))
    report = {
        'completed_utc': utc_now(), 'freeze_sha256': digest(output / 'frozen.json'),
        'case_results_sha256': digest(records), 'model': config.model,
        'model_revision': frozen['model_manifest']['revision'],
        'count': total, 'structural_passes': counts['passed'],
        'per_kind': per_kind, 'families_count': len(family_kinds),
        'three_families_four_types': family_matrix,
        'code_unchanged': code_unchanged, 'cases_unchanged': cases_unchanged,
        'model_manifest_unchanged': manifest_unchanged,
        'gate_11_of_12_each_type': gate,
        'elapsed_seconds': round(time.perf_counter() - started, 3),
        'limitations': ['Автоматическая проверка не подтверждает правильность ответа, рубрики или грейда.',
                        'Человеческая проверка содержания обязательна.'],
    }
    with (output / 'report.json').open('x', encoding='utf-8') as target:
        json.dump(report, target, ensure_ascii=False, indent=2)
        target.write('\n')
    print(json.dumps({'out_dir': str(output), 'count': total,
                      'structural_passes': counts['passed'], 'gate': gate}, ensure_ascii=False))
    return report


def main():
    parser = argparse.ArgumentParser(description='Оценка локальных LLM-черновиков без повторных запросов')
    parser.add_argument('--cases', required=True, help='JSON-объект с массивом cases')
    parser.add_argument('--out-dir', required=True, help='Новый прямой подкаталог ml/runs')
    parser.add_argument('--model-manifest', required=True, help='Manifest закреплённой модели')
    evaluate(parser.parse_args())


if __name__ == '__main__':
    main()

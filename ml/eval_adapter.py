"""Однократная оценка базовой модели и/или LoRA-адаптера теми же средствами, что и продукт.

Используются LocalRuntime (NF4, CUDA:0, LMFE-схема), системный prompt и пользовательское сообщение
продукта, проверки _checked_generated_shape/_checked_task. Автопроверка смысла возможна только там,
где бриф фиксирует вопрос: числовой ответ и ключевой вариант одиночного выбора сверяются с эталоном.
Остальное — ручной просмотр. Запускать в GPU-контейнере без сети (ml/dr.sh --gpu).
"""
import argparse
import hashlib
import json
import time
from pathlib import Path

from src.server import bank_generation as bg
from ml.corpus.core import request_for
from ml.local_model import LocalRuntime, Message, MODEL_ID


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def auto_check(task, check):
    """Вернуть (True/False/None, пояснение); None — автопроверка неприменима."""
    if not check:
        return None, ''
    if 'value' in check:
        value = task.get('numeric_answer')
        ok = isinstance(value, (int, float)) and abs(value - check['value']) < 1e-9
        return ok, f'numeric_answer={value}, ожидалось {check["value"]}'
    if 'contains' in check:
        key = set(task.get('answer_key', []))
        options = {o['id']: o['text'] for o in task.get('options', [])}
        if len(key) != 1:
            return False, 'ключ не один'
        text = options[next(iter(key))]
        has = lambda s: all(part in s for part in check['contains'])
        others = [t for i, t in options.items() if i not in key]
        ok = has(text) and not any(has(t) for t in others)
        return ok, f'ключ: {text!r}'
    return None, ''


def run(args):
    cases = json.loads(Path(args.cases).read_text(encoding='utf-8'))['cases']
    checks = {}
    if args.checks:
        checks = json.loads(Path(args.checks).read_text(encoding='utf-8'))['checks']
    out = Path(args.output)
    if out.exists():
        raise SystemExit('Файл результата уже существует')
    out.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    runtime = LocalRuntime(Path(args.model), Path(args.manifest),
                           Path(args.adapter) if args.adapter else None,
                           Path(args.adapter_manifest) if args.adapter else None)
    load_seconds = time.time() - started
    rows = []
    for case in cases:
        request = request_for(case['kind'], case['specialization'], case['grade'], case['skills'], case['brief'])
        system, user = bg.request_messages(request, args.profile, serving=True)
        messages = [Message(role='system', content=system), Message(role='user', content=user)]
        schema = bg.task_generation_schema(request.kind, request.skills)
        t0 = time.time()
        row = {'id': case['id'], 'family': case.get('family'), 'kind': case['kind']}
        try:
            text = runtime.complete(messages, schema, 1280)
            row['raw'] = text
            raw = json.loads(text)
            bg._checked_generated_shape(raw, request.kind, request.skills, serving=True)
            bg._checked_task(raw, request)
            row['structural'] = True
            ok, note = auto_check(bg._prepare_raw(raw), checks.get(case['id']))
            row['auto_semantic'] = ok
            row['auto_note'] = note
        except Exception as error:  # noqa: BLE001
            row['structural'] = False
            row['error'] = type(error).__name__ + ': ' + str(error)[:200]
        row['seconds'] = round(time.time() - t0, 2)
        rows.append(row)
        print(json.dumps({k: row[k] for k in ('id', 'structural', 'seconds')} | {'auto': row.get('auto_semantic')}), flush=True)
    summary = {
        'schema': 'fsp-adapter-eval-v1', 'generation_schema': 'serving-v4',
        'profile': args.profile, 'model': MODEL_ID, 'adapter': args.adapter,
        'cases_sha256': digest(args.cases), 'checks_sha256': digest(args.checks) if args.checks else None,
        'load_seconds': round(load_seconds, 1), 'count': len(rows),
        'structural_passes': sum(r['structural'] for r in rows),
        'auto_checked': sum(r.get('auto_semantic') is not None for r in rows),
        'auto_passes': sum(r.get('auto_semantic') is True for r in rows),
        'per_kind': {k: [sum(r['structural'] for r in rows if r['kind'] == k), sum(r['kind'] == k for r in rows)]
                     for k in sorted({r['kind'] for r in rows})},
        'seconds': round(time.time() - started, 1),
    }
    out.write_text(json.dumps({'summary': summary, 'rows': rows}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--adapter')
    parser.add_argument('--adapter-manifest')
    parser.add_argument('--cases', required=True)
    parser.add_argument('--checks')
    parser.add_argument('--profile', choices=['base', 'tuned'], default='base')
    parser.add_argument('--output', required=True)
    run(parser.parse_args())

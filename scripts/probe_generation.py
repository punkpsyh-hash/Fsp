"""Проба четырёх типов черновиков на локальной модели; не калибровка качества."""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.local_model import MODEL_REVISION
from src.server.bank_generation import GenerationRequest, _local_endpoint, generate_task
from src.server.llm import LLMConfig

BRIEFS = {
    'single_choice': 'Короткое задание Python про len множества с повторяющимися целыми числами. Эталон вычисли точно.',
    'multiple_choice': 'Короткое задание Python: какие операции изменяют список на месте. Используй append, sort, sorted, len.',
    'numeric': 'Короткое задание Python: сумма трёх явно указанных небольших целых чисел из списка. Единица — число.',
    'open_response': 'Объяснить, как ключ идемпотентности предотвращает повторное создание платежа при повторе HTTP-запроса. Рубрика: 0/50/100.',
}


def run(base_url, model, timeout):
    if not _local_endpoint(base_url):
        raise ValueError('Проба разрешена только для локального сервера модели')
    config = LLMConfig('openai-compatible', base_url, model, '', timeout, timeout)
    health = httpx.get(base_url.removesuffix('/').removesuffix('/v1') + '/health', timeout=10)
    health.raise_for_status()
    ready = health.json()
    if not isinstance(ready, dict) or (ready.get('status'), ready.get('model'), ready.get('revision')) != (
            'ready', model, MODEL_REVISION):
        raise RuntimeError('Health не подтверждает готовность закреплённой модели')
    report = {'protocol': '4 типа / до 8 inference-попыток при отказах схемы; черновики проверяет человек',
              'model': model, 'health': ready, 'rows': []}
    for kind, brief in BRIEFS.items():
        started = time.monotonic()
        row = {'kind': kind, 'brief': brief}
        try:
            request = GenerationRequest(kind=kind, specialization='backend', grade='junior',
                                        skills=['http' if kind == 'open_response' else 'python'], brief=brief)
            result = generate_task(request, config)
            row['result'] = result.model_dump(mode='json')
        except Exception as error:  # отказ тоже результат пробы; сырой текст ошибки не сохраняется
            row['error'] = type(error).__name__
        row['seconds'] = round(time.monotonic() - started, 3)
        report['rows'].append(row)
    report['accepted'] = sum('result' in row for row in report['rows'])
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--model', default='Qwen/Qwen3-4B-Instruct-2507')
    parser.add_argument('--timeout', type=float, default=100)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = run(args.base_url, args.model, args.timeout)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'accepted': report['accepted'], 'total': len(report['rows'])}))
    raise SystemExit(0 if report['accepted'] == len(BRIEFS) else 1)

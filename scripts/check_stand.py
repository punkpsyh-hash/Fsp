"""Проверка API/БД и готовности локальной модели без передачи задания и ключей в вывод."""
import json
import argparse
from urllib.parse import urlparse

import httpx

from src.server.llm import config_from_env


def check(require_local_llm=False):
    with httpx.Client(trust_env=False, timeout=10) as client:
        response = client.get('http://127.0.0.1:8470/api/health')
        response.raise_for_status()
        if response.json().get('status') != 'ok':
            raise ValueError('API не готов')
        result = {'api_and_database': 'ready'}
        config = config_from_env()
        if require_local_llm and (config.provider != 'openai-compatible'
                                  or urlparse(config.base_url).hostname != 'model'):
            raise ValueError('Приложение запущено без локальной Compose-модели')
        result['llm_provider'] = config.provider
        if config.provider == 'openai-compatible':
            result['llm_key_configured'] = bool(config.api_key)
            if urlparse(config.base_url).hostname == 'model':
                health = client.get(config.base_url.rsplit('/v1', 1)[0] + '/health')
                health.raise_for_status()
                payload = health.json()
                if (payload.get('status') != 'ready'
                        or payload.get('model') != 'Qwen/Qwen3-4B-Instruct-2507'
                        or payload.get('revision') != 'cdbee75f17c01a7cc42f958dc650907174af0554'
                        or payload.get('adapter')
                        or payload.get('quantization', {}).get('type') != 'nf4'
                        or payload.get('quantization', {}).get('placement') != 'cuda:0'):
                    raise ValueError('Локальная модель не соответствует выпуску')
                if not config.api_key:
                    raise ValueError('Не настроен ключ локальной модели')
                # Неподдерживаемый служебный запрос проверяет ключ без инференса.
                probe = client.post(config.base_url.rstrip('/') + '/chat/completions',
                                    headers={'Authorization': 'Bearer ' + config.api_key},
                                    json={'model': config.model, 'messages': [
                                        {'role': 'system', 'content': 'Ответь JSON по заданной схеме.'},
                                        {'role': 'user', 'content': 'Проверка доступа'}],
                                        'max_tokens': 24, 'temperature': 0,
                                        'response_format': {'type': 'json_schema', 'json_schema': {
                                            'name': 'task_draft', 'strict': True, 'schema': {
                                                'type': 'object', 'properties': {'status': {
                                                    'type': 'string', 'enum': ['ready']}},
                                                'required': ['status'], 'additionalProperties': False}}}})
                if (probe.status_code != 422
                        or probe.json().get('detail') != {'code': 'input_rejected'}):
                    raise ValueError('Ключ локальной модели не принят')
                result['local_model'] = 'ready'
            else:
                result['connector'] = 'configured; inference requires a task in the constructor'
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-local-llm', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.require_local_llm), ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'ready': False, 'error_type': type(error).__name__}))
        raise SystemExit(1)

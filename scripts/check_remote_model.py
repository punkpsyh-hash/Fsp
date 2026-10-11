"""Проверить точную модель, SSH Unix socket и обязательную авторизацию, не выводя ключ."""
import argparse
import json
import os

import httpx


def check(socket_path, api_key, health_only=False):
    expected_model = 'Qwen/Qwen3-4B-Instruct-2507'
    expected_revision = 'cdbee75f17c01a7cc42f958dc650907174af0554'
    with httpx.Client(transport=httpx.HTTPTransport(uds=socket_path), trust_env=False, timeout=120) as client:
        response = client.get('http://local-model.internal/health', timeout=10)
        response.raise_for_status()
        health = response.json()
        valid = (health.get('status') == 'ready' and health.get('model') == expected_model
                 and health.get('revision') == expected_revision and not health.get('adapter')
                 and health.get('quantization', {}).get('type') == 'nf4'
                 and health.get('quantization', {}).get('placement') == 'cuda:0')
        result = {'identity_verified': valid, 'model': health.get('model'), 'revision': health.get('revision')}
        if not valid or health_only:
            return result, valid
        if not api_key:
            return {**result, 'key_configured': False}, False
        payload = {'model': expected_model, 'messages': [{'role': 'system', 'content': 'Ответь JSON по заданной схеме.'},
                   {'role': 'user', 'content': 'Верни status ready.'}],
                   'max_tokens': 64, 'temperature': 0,
                   'response_format': {'type': 'json_schema', 'json_schema': {'name': 'task_draft',
                     'strict': True, 'schema': {'type': 'object', 'properties': {
                         'status': {'type': 'string', 'enum': ['ready']}}, 'required': ['status'],
                         'additionalProperties': False}}}}
        unauthorized = client.post('http://local-model.internal/v1/chat/completions', json=payload)
        authorized = client.post('http://local-model.internal/v1/chat/completions', json=payload,
                                 headers={'Authorization': 'Bearer ' + api_key})
        # Эта намеренно неподдерживаемая схема проверяет доступ без запуска
        # генерации: без ключа 401, с правильным ключом input_rejected 422.
        # Живой инференс проверяется отдельным продуктовым прогоном.
        authenticated = (authorized.status_code == 422
                         and authorized.json().get('detail') == {'code': 'input_rejected'})
        result = {**result, 'unauthorized_status': unauthorized.status_code,
                  'authorized_status': authorized.status_code, 'authenticated_access': authenticated}
        return result, unauthorized.status_code == 401 and authenticated


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--health-only', action='store_true')
    args = parser.parse_args()
    try:
        result, valid = check(os.environ.get('FSP_LLM_SOCKET_PATH', '/model-tunnel/gpu.sock'),
                              os.environ.get('FSP_LLM_API_KEY', ''), args.health_only)
    except Exception as error:
        result, valid = {'connection_verified': False, 'error_type': type(error).__name__}, False
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if valid else 1)

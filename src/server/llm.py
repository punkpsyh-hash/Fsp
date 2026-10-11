"""Необязательный ИИ-помощник: словесное объяснение подборки работодателю.

Границы (подробно в docs/29-llm.md):
* по умолчанию выключен: FSP_LLM_PROVIDER не задан, всё работает без внешних вызовов;
* модель ничего не решает: не ставит грейд, не меняет ранжирование, не видит ПДн;
* в запрос уходят только факты из белого списка (баллы, навыки, статусы), без имени,
  контактов, резюме и свободного текста; для свободного текста есть redact();
* ответ проверяется: числа и навыки должны совпадать с фактами, иначе используется
  детерминированный шаблон. Шаблон же — ответ при любой ошибке и таймауте;
* провайдер — любой OpenAI-совместимый сервер (локальная открытая модель на vLLM/Ollama
  или российский облачный шлюз), ключ только из переменной окружения.
"""
from dataclasses import dataclass
import ipaddress
import os
import re
from urllib.parse import urlparse

import httpx

SKILL_WORDS = {'python', 'sql', 'http', 'javascript', 'html', 'testing'}
SYSTEM_PROMPT = (
    'Ты помощник работодателя на ИТ-платформе. По фактам из JSON объясни по-русски в двух-трёх '
    'предложениях, почему кандидат попал в подборку. Используй только факты из JSON, ничего не '
    'добавляй и не округляй числа. Не оценивай личные качества. Не упоминай, что ты модель.'
)
GRADE_NAMES = {'junior': 'Junior', 'middle': 'Middle', None: 'не подтверждён'}
SPECIALIZATION_NAMES = {'backend': 'Backend', 'frontend': 'Frontend', 'qa': 'QA', 'design': 'UI/UX дизайн'}
FSP_NAMES = {'none': 'связь с ФСП не настроена', 'linked-empty': 'в ФСП ID истории участия нет',
             'verified': 'есть подтверждённые достижения ФСП (демо-источник)',
             'unavailable': 'данные ФСП временно недоступны'}


@dataclass(frozen=True)
class LLMConfig:
    provider: str = 'none'
    base_url: str = ''
    model: str = ''
    api_key: str = ''
    timeout: float = 8.0
    # Генерация задания занимает десятки секунд; короткий лимит нужен только объяснениям подборки.
    generation_timeout: float = 100.0
    socket_path: str = ''

    @property
    def enabled(self):
        return self.provider in {'mock', 'openai-compatible'}


def config_from_env(env=None):
    env = os.environ if env is None else env
    provider = env.get('FSP_LLM_PROVIDER', 'none')
    if provider not in {'none', 'mock', 'openai-compatible'}:
        raise ValueError('FSP_LLM_PROVIDER: none, mock или openai-compatible')
    config = LLMConfig(provider, env.get('FSP_LLM_BASE_URL', ''), env.get('FSP_LLM_MODEL', ''),
                       env.get('FSP_LLM_API_KEY', ''), float(env.get('FSP_LLM_TIMEOUT', '8')),
                       float(env.get('FSP_LLM_GENERATION_TIMEOUT', '100')),
                       env.get('FSP_LLM_SOCKET_PATH', ''))
    if config.socket_path and (not config.socket_path.startswith('/') or not config.socket_path.endswith('.sock')):
        raise ValueError('FSP_LLM_SOCKET_PATH должен быть абсолютным путём Unix socket .sock')
    if not 0 < config.generation_timeout <= 120:
        raise ValueError('FSP_LLM_GENERATION_TIMEOUT должен быть больше 0 и не больше 120 секунд')
    if provider == 'openai-compatible':
        check_endpoint(config.base_url)
        if not config.model:
            raise ValueError('FSP_LLM_MODEL обязателен')
    return config


def check_endpoint(base_url):
    """https обязателен; http допускается только для локального/внутреннего адреса."""
    parsed = urlparse(base_url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise ValueError('FSP_LLM_BASE_URL должен быть http(s)-адресом')
    if parsed.scheme == 'https':
        return
    host = parsed.hostname
    try:
        local = ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == 'localhost' or host.endswith('.internal') or '.' not in host
    if not local:
        raise ValueError('Внешний LLM-сервер допустим только по https')


def redact(text, limit=2000):
    """Убирает типичные ПДн из свободного текста перед любой передачей наружу."""
    text = re.sub(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+', '[email]', text)
    text = re.sub(r'https?://\S+|\bwww\.\S+', '[ссылка]', text)
    text = re.sub(r'(?<!\w)(?:\+7|8)[\s(.-]*\d{3}[\s).-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)', '[телефон]', text)
    text = re.sub(r'\b\d{6,}\b', '[число]', text)
    return text[:limit]


def facts_for(row):
    """Белый список полей строки подборки; всё остальное в модель не попадает."""
    components = row.get('components') or {}
    works = [{'task': w.get('label'), 'status': w.get('status'), 'missing_skills': w.get('missing_skills', [])}
             for w in row.get('work_matches') or []]
    return {
        'specialization': SPECIALIZATION_NAMES.get(row.get('specialization'), 'ИТ'),
        'confirmed_grade': GRADE_NAMES.get(row.get('confirmed_grade'), 'не подтверждён'),
        'assessment_score_of_100': row.get('test_score'),
        'total_rank_score': row.get('score'),
        'rank_components': {'assessment': components.get('assessment'), 'skills': components.get('skills'),
                            'fsp': components.get('fsp'), 'freshness': components.get('freshness')},
        'matched_skills': row.get('matched', []),
        'missing_skills': row.get('missing', []),
        'team_tasks': works,
        'fsp': FSP_NAMES.get(row.get('fsp_state'), FSP_NAMES['none']),
        'integrity': {'clean': 'без замечаний при тесте', 'review': 'при тесте есть замечания',
                      'flagged': 'при тесте есть замечания'}.get(row.get('integrity_level')),
    }


def _num(value):
    return f'{value:g}'.replace('.', ',') if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)


def template_text(facts):
    """Детерминированное объяснение: единственный источник при выключенной модели."""
    parts = [f"{facts['specialization']}, уровень {facts['confirmed_grade']}, оценка теста {_num(facts['assessment_score_of_100'])} из 100."]
    matched, missing = facts['matched_skills'], facts['missing_skills']
    parts.append('Подтверждены навыки: ' + (', '.join(matched) if matched else 'нет совпадений') +
                 ('; не подтверждены: ' + ', '.join(missing) if missing else '; все нужные навыки покрыты') + '.')
    c = facts['rank_components']
    parts.append(f"Итоговый балл {_num(facts['total_rank_score'])}: оценка {_num(c['assessment'])}, навыки {_num(c['skills'])}, "
                 f"ФСП {_num(c['fsp'])}, актуальность {_num(c['freshness'])}; {facts['fsp']}.")
    if facts['integrity']:
        parts.append(facts['integrity'].capitalize() + '.')
    return ' '.join(parts)


def _numbers(text):
    return set(re.findall(r'\d+(?:[.,]\d+)?', text.replace(' ', ' ')))


def validate(output, facts):
    """Ответ модели допустим, если не содержит чисел и навыков вне фактов."""
    allowed = {n.replace(',', '.') for n in _numbers(template_text(facts) + ' ' + str(facts))}
    if any(n.replace(',', '.') not in allowed for n in _numbers(output)):
        return 'numbers'
    known = {s.lower() for s in facts['matched_skills'] + facts['missing_skills']}
    if any(word in SKILL_WORDS - known for word in re.findall(r'[a-z]+', output.lower())):
        return 'skills'
    if not 20 <= len(output) <= 900:
        return 'length'
    return None


class MockProvider:
    """Локальная заглушка для демонстрации без внешних вызовов: пересказывает факты."""
    model = 'mock-rephraser'

    def complete(self, system, user, max_tokens=220, temperature=0.2):
        return 'Кратко: ' + user_facts_sentence(user)


def user_facts_sentence(user):
    import json
    facts = json.loads(user)
    matched = ', '.join(facts['matched_skills']) or 'нет совпадений'
    return (f"{facts['specialization']} {facts['confirmed_grade']}, тест {_num(facts['assessment_score_of_100'])} из 100; "
            f"совпали навыки: {matched}. Итоговый балл {_num(facts['total_rank_score'])}.")


class OpenAICompatible:
    def __init__(self, config):
        self.config, self.model = config, config.model

    def _post(self, **kwargs):
        url = self.config.base_url.rstrip('/') + '/chat/completions'
        if not self.config.socket_path:
            return httpx.post(url, **kwargs)
        # NAS подключается к GPU через отдельный SSH Unix socket. Сетевой
        # адрес модели остаётся локальным, Docker socket здесь не используется.
        with httpx.Client(transport=httpx.HTTPTransport(uds=self.config.socket_path), trust_env=False) as client:
            return client.post(url, **kwargs)

    def complete(self, system, user, max_tokens=220, temperature=0.2):
        headers = {'Authorization': 'Bearer ' + self.config.api_key} if self.config.api_key else {}
        response = self._post(headers=headers,
                              timeout=self.config.timeout, json={
                                  'model': self.config.model, 'temperature': temperature, 'max_tokens': max_tokens,
                                  'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]})
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()

    def complete_structured(self, system, user, schema, max_tokens=768, temperature=0.2):
        """Запросить JSON Schema; обычные объяснения используют прежний complete()."""
        headers = {'Authorization': 'Bearer ' + self.config.api_key} if self.config.api_key else {}
        response = self._post(headers=headers,
                              timeout=self.config.generation_timeout, json={
                                  'model': self.config.model, 'temperature': temperature, 'max_tokens': max_tokens,
                                  'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                                  'response_format': {'type': 'json_schema', 'json_schema': {
                                      'name': 'task_draft', 'strict': True, 'schema': schema}}})
        response.raise_for_status()
        choice = response.json()['choices'][0]
        if choice.get('finish_reason') != 'stop' or not isinstance(choice.get('message', {}).get('content'), str):
            raise ValueError('Структурированный ответ модели не завершён')
        return choice['message']['content'].strip()


def provider_for(config):
    if config.provider == 'mock':
        return MockProvider()
    if config.provider == 'openai-compatible':
        return OpenAICompatible(config)
    return None


def explain(row, config=None, provider=None):
    """Возвращает {'text', 'source', 'model', 'fallback_reason'}; никогда не бросает из-за модели."""
    config = config or config_from_env()
    facts = facts_for(row)
    base = {'text': template_text(facts), 'source': 'template', 'model': None, 'fallback_reason': None}
    provider = provider or provider_for(config)
    if provider is None:
        return base
    import json
    try:
        output = provider.complete(SYSTEM_PROMPT, json.dumps(facts, ensure_ascii=False)).strip()
    except Exception as error:  # сеть, таймаут, формат ответа: объяснение не должно пропадать
        return {**base, 'fallback_reason': 'unavailable:' + type(error).__name__}
    problem = validate(output, facts)
    if problem:
        return {**base, 'fallback_reason': 'rejected:' + problem}
    return {'text': output, 'source': 'llm-mock' if config.provider == 'mock' else 'llm',
            'model': provider.model, 'fallback_reason': None}

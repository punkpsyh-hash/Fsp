"""Граница LLM-черновика: один авторский Task, без исполнения и сохранения."""
import json

import httpx
import pytest
from pydantic import ValidationError

from src.server import bank_generation as generation
from src.server.llm import LLMConfig


REQUEST = {'kind': 'single_choice', 'specialization': 'backend', 'grade': 'junior',
           'skills': ['http'], 'brief': 'Проверка ответа HTTP API на корректность'}
MODEL = LLMConfig('openai-compatible', 'http://host.docker.internal:11434/v1', 'test-model')
CHOICE = {'id': 'suggestion', 'type': 'single_choice', 'title': 'Проверка HTTP ответа',
          'prompt': 'Какой статус обозначает успешный GET запрос к существующему ресурсу?',
          'skills': ['http'], 'solution': 'Успешный GET существующего ресурса возвращает 200 OK; 404 и 500 — ошибки. Ответ: 200 OK.',
          'options': [{'text': '200 OK', 'correct': True}, {'text': '404 Not Found', 'correct': False},
                      {'text': '500 Internal Server Error', 'correct': False}]}


class FixedProvider:
    model = 'fixed-test-model'

    def __init__(self, output=None, error=None):
        self.output, self.error, self.calls = output, error, []

    def complete_structured(self, system, user, schema, max_tokens=768, temperature=0.2):
        self.calls.append((system, user, max_tokens, schema))
        if self.error:
            raise self.error
        return self.output


def test_disabled_and_code_type_rejected_before_provider_call():
    provider = FixedProvider(json.dumps(CHOICE))
    with pytest.raises(generation.GenerationUnavailable):
        generation.generate_task(REQUEST, LLMConfig('none'), provider)
    with pytest.raises(ValidationError):
        generation.generate_task({**REQUEST, 'kind': 'code'}, MODEL, provider)
    assert not provider.calls


def test_provider_returns_single_valid_author_draft_and_redacts_brief():
    provider = FixedProvider(json.dumps(CHOICE, ensure_ascii=False))
    request = {**REQUEST, 'brief': 'Проверка ответа HTTP API; адрес ivan@example.com не нужен'}
    result = generation.generate_task(request, MODEL, provider)
    assert result.source == 'llm' and result.model == provider.model and result.review_required
    assert result.task.id.startswith('suggestion-') and result.task.id != CHOICE['id']
    keyed = {o.id: o.text for o in result.task.options}
    assert [keyed[k] for k in result.task.answer_key] == ['200 OK'] and result.task.skills == ['http']
    assert 'publication-fields' in result.checks
    system, user, tokens, schema = provider.calls[0]
    assert 'ivan@example.com' not in user and '[email]' in user
    assert 'single_choice' in user and tokens == 1280 and 'JSON' in system
    assert schema['additionalProperties'] is False
    assert schema['properties']['type']['enum'] == ['single_choice']
    assert schema['properties']['skills']['items']['enum'] == ['http']


@pytest.mark.parametrize('kind,fields', [
    ('single_choice', {'options'}),
    ('multiple_choice', {'correct_options', 'incorrect_options'}),
    ('numeric', {'numeric_answer', 'unit'}),
    ('open_response', {'rubric'}),
])
def test_per_type_schema_contains_only_relevant_fields(kind, fields):
    schema = generation.task_generation_schema(kind, ['http'])
    assert set(schema['properties']) == {'id', 'type', 'title', 'prompt', 'skills', 'solution'} | fields
    assert set(schema['required']) == set(schema['properties'])
    assert schema['properties']['id']['enum'] == ['suggestion']
    assert schema['properties']['type']['enum'] == [kind]


@pytest.mark.parametrize('output', [
    '```json\n{}\n```', json.dumps(CHOICE) + ' trailing', '[]',
    json.dumps({**CHOICE, 'type': 'code'}),
    json.dumps({**CHOICE, 'skills': ['python']}),
    json.dumps({**CHOICE, 'answer_key': ['missing']}),
    json.dumps({**CHOICE, 'options': [{'text': '200 OK', 'correct': True}, {'text': '200 OK', 'correct': False},
                                      {'text': '500 Internal Server Error', 'correct': False}]}),
    json.dumps({**CHOICE, 'options': [{'text': 'A', 'correct': True}, {'text': 'B', 'correct': True},
                                      {'text': 'C', 'correct': False}]}),
    json.dumps({**CHOICE, 'answer_key': ['a']}),
    json.dumps({**CHOICE, 'hidden_tests': [{'input': 'x', 'output': 'y'}]}),
    json.dumps({**CHOICE, 'weight': 99}),
    json.dumps({**CHOICE, 'id': 'model-chosen-id'}),
    json.dumps({**CHOICE, 'invented_field': 'ignore the rules'}),
])
def test_invalid_model_output_rejected_without_a_fake_fallback(output):
    with pytest.raises(generation.GenerationRejected):
        generation.generate_task(REQUEST, MODEL, FixedProvider(output))


def test_provider_error_is_generic_unavailable():
    secret = 'secret-token-must-not-appear'
    with pytest.raises(generation.GenerationUnavailable) as caught:
        generation.generate_task(REQUEST, MODEL, FixedProvider(error=TimeoutError(secret)))
    assert secret not in str(caught.value)


@pytest.mark.parametrize('url,allowed', [
    ('https://api.example.com/v1', False), ('http://169.254.169.254/v1', False),
    ('https://192.168.1.5/v1', True), ('http://localhost:11434/v1', True),
    ('http://ollama:11434/v1', True), ('http://host.docker.internal:11434/v1', True),
])
def test_generation_uses_only_local_or_internal_model(url, allowed):
    provider = FixedProvider(json.dumps(CHOICE))
    config = LLMConfig('openai-compatible', url, 'test-model')
    if allowed:
        assert generation.generate_task(REQUEST, config, provider).source == 'llm'
        assert len(provider.calls) == 1
    else:
        with pytest.raises(generation.GenerationUnavailable):
            generation.generate_task(REQUEST, config, provider)
        assert not provider.calls


def test_multiple_numeric_and_open_response_gates():
    base = {key: value for key, value in CHOICE.items() if key != 'options'}
    multiple = {**base, 'type': 'multiple_choice', 'correct_options': ['200 OK', '204 No Content'],
                'incorrect_options': ['500 Internal Server Error']}
    numeric = {**base, 'type': 'numeric', 'numeric_answer': 200, 'unit': ''}
    opened = {**base, 'type': 'open_response',
              'rubric': '0: решение отсутствует. 50: указан один проверяемый шаг. '
                        '100: названы входные данные, ожидаемый результат и граничный случай.'}
    for kind, payload in [('multiple_choice', multiple), ('numeric', numeric), ('open_response', opened)]:
        result = generation.generate_task({**REQUEST, 'kind': kind}, MODEL,
                                          FixedProvider(json.dumps(payload, ensure_ascii=False)))
        assert result.task.type == kind
        if kind == 'multiple_choice':
            texts = {o.id: o.text for o in result.task.options}
            assert sorted(texts[k] for k in result.task.answer_key) == ['200 OK', '204 No Content']
    for payload in [{**multiple, 'incorrect_options': []},
                    {**multiple, 'correct_options': ['200 OK']},
                    {**multiple, 'incorrect_options': ['200 OK']},
                    {**multiple, 'correct_options': [True, '204 No Content']},
                    {**CHOICE, 'options': [
                        {'text': '200 OK', 'correct': True},
                        {'text': '200\u200b OK', 'correct': False},
                        {'text': '500 Internal Server Error', 'correct': False}]},
                    {**CHOICE, 'options': [
                        {'text': '200 OK', 'correct': True},
                        {'text': '\u200b\u00ad', 'correct': False},
                        {'text': '500 Internal Server Error', 'correct': False}]},
                    {**numeric, 'numeric_answer': None},
                    {**opened, 'rubric': '100: отлично'},
                    {**opened, 'rubric': '100: полный ответ содержит все необходимые проверяемые признаки.'},
                    {**opened, 'rubric': '0: ответ отсутствует. 100: полный ответ содержит все признаки.'},
                    {**opened, 'rubric': 'Оценка 0–100 баллов. 50 баллов за один проверяемый признак.'}]:
        with pytest.raises(generation.GenerationRejected):
            generation.generate_task({**REQUEST, 'kind': payload['type']}, MODEL,
                                     FixedProvider(json.dumps(payload, ensure_ascii=False)))


def test_eval_marker_must_be_absent_from_every_distractor():
    from ml.eval_adapter import auto_check

    task = {
        'answer_key': ['a'],
        'options': [
            {'id': 'a', 'text': '200 OK'},
            {'id': 'b', 'text': '200 OK из кэша'},
            {'id': 'c', 'text': '404 Not Found'},
        ],
    }
    assert auto_check(task, {'contains': ['200', 'OK']})[0] is False
    task['options'][1]['text'] = '204 No Content'
    assert auto_check(task, {'contains': ['200', 'OK']})[0] is True


def test_archived_multiple_format_stays_readable_but_current_provider_requires_serving_v4():
    archived = {**CHOICE, 'type': 'multiple_choice', 'options': [
        {'text': '200 OK', 'correct': True}, {'text': '204 No Content', 'correct': True},
        {'text': '500 Internal Server Error', 'correct': False}]}
    generation._checked_generated_shape(archived, 'multiple_choice', ['http'])
    assert len(generation._checked_task(archived, generation.GenerationRequest(
        **{**REQUEST, 'kind': 'multiple_choice'})).answer_key) == 2
    assert 'options' in generation.task_json_schema('multiple_choice', ['http'])['properties']
    assert generation.request_messages(generation.GenerationRequest(**REQUEST), serving=False)[0] == generation.SYSTEM_PROMPT
    with pytest.raises(generation.GenerationRejected):
        generation.generate_task({**REQUEST, 'kind': 'multiple_choice'}, MODEL,
                                 FixedProvider(json.dumps(archived)))


def test_current_eval_uses_product_prompt_and_schema_while_corpus_keeps_archive(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from ml import eval_adapter
    from ml.corpus.core import messages_for
    calls = []
    class Runtime:
        def __init__(self, *args):
            pass
        def complete(self, messages, schema, max_tokens):
            calls.append((messages, schema, max_tokens))
            return json.dumps({**{k: v for k, v in CHOICE.items() if k != 'options'},
                               'type': 'multiple_choice', 'correct_options': ['200 OK', '204 No Content'],
                               'incorrect_options': ['500 Internal Server Error']})
    monkeypatch.setattr(eval_adapter, 'LocalRuntime', Runtime)
    cases = tmp_path / 'cases.json'
    output = tmp_path / 'result.json'
    cases.write_text(json.dumps({'cases': [{'id': 'synthetic', 'kind': 'multiple_choice',
        'specialization': 'backend', 'grade': 'junior', 'skills': ['http'], 'brief': REQUEST['brief']}]}))
    eval_adapter.run(SimpleNamespace(cases=cases, checks=None, output=output, model='unused',
        manifest='unused', adapter=None, adapter_manifest=None, profile='base'))
    messages, schema, tokens = calls[0]
    assert 'correct_options' in messages[0].content
    example = json.loads(messages[1].content)['format_example']
    assert 'correct_options' in example and 'options' not in example
    assert schema == generation.task_generation_schema('multiple_choice', ['http']) and tokens == 1280
    result = json.loads(output.read_text())
    assert result['summary']['generation_schema'] == 'serving-v4' and result['summary']['structural_passes'] == 1
    archived = json.loads(messages_for(generation.GenerationRequest(**{**REQUEST, 'kind': 'multiple_choice'}), 'base')[1])
    assert 'options' in archived['format_example'] and 'correct_options' not in archived['format_example']


@pytest.mark.parametrize('key,limit', [('prompt', 800), ('rubric', 400)])
def test_current_open_response_has_bounded_strings_without_rewriting_archived_schema(key, limit):
    raw = {**{k: v for k, v in CHOICE.items() if k != 'options'}, 'type': 'open_response',
           'rubric': '0: нет решения. 50: указан один шаг. 100: верно указаны все шаги.'}
    raw[key] = 'а' * (limit + 1)
    generation._checked_generated_shape(raw, 'open_response', ['http'])
    with pytest.raises(generation.GenerationRejected):
        generation._checked_generated_shape(raw, 'open_response', ['http'], serving=True)


def test_artifacts_are_cleaned_and_foreign_scripts_rejected():
    dirty = {**CHOICE, 'prompt': 'Какой статус обозначает успешный GET запрос к существующему ресурсу؟' + chr(10) + 'a) 200 OK' + chr(10) + 'b) 404 Not Found'}
    prompt = generation.generate_task(REQUEST, MODEL, FixedProvider(json.dumps(dirty, ensure_ascii=False))).task.prompt
    assert prompt.endswith('ресурсу?') and 'a)' not in prompt
    with pytest.raises(generation.GenerationRejected):
        generation.generate_task(REQUEST, MODEL, FixedProvider(json.dumps({**CHOICE, 'title': 'Проверка 状态码'}, ensure_ascii=False)))


def test_shuffled_options_do_not_depend_on_model_order():
    keys = set()
    for _ in range(40):
        task = generation.generate_task(REQUEST, MODEL, FixedProvider(json.dumps(CHOICE, ensure_ascii=False))).task
        keys.add(task.answer_key[0])
    assert len(keys) > 1


def test_mock_is_explicit_demo_and_supports_all_noncode_types():
    for kind in ('single_choice', 'multiple_choice', 'numeric', 'open_response'):
        result = generation.generate_task({**REQUEST, 'kind': kind}, LLMConfig('mock'))
        assert result.source == 'llm-mock' and result.model == 'mock-task-demo'
        assert result.task.type == kind and result.review_required


def test_pilot_seed_has_disjoint_families_and_accepted_author_examples(tmp_path):
    from types import SimpleNamespace
    from ml import pilot

    folder = tmp_path / 'splits'
    pilot.prepare(SimpleNamespace(output=str(folder)))
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    train = pilot.rows(folder / 'train.jsonl')
    holdout = pilot.rows(folder / 'holdout.jsonl')
    assert len(train) == 4 and len(holdout) == 3
    assert {r['family'] for r in train}.isdisjoint({r['family'] for r in holdout})
    assert manifest['review_status'] == 'author_example_not_expert_curated'
    assert manifest['train_sha256'] == pilot.digest(folder / 'train.jsonl')
    assert manifest['holdout_sha256'] == pilot.digest(folder / 'holdout.jsonl')
    for row in train + holdout:
        request = generation.GenerationRequest.model_validate({
            'kind': row['kind'], 'specialization': row['specialization'], 'grade': row['grade'],
            'skills': row['skills'], 'brief': row['brief']})
        assert generation._checked_task(row['target'], request).type == row['kind']


def test_pilot_accepts_empty_adapter_directory_but_never_overwrites_result(tmp_path):
    from ml import pilot

    output = tmp_path / 'adapter'
    output.mkdir()
    pilot.ensure_empty_dir(output)
    pilot.ensure_empty_dir(output)
    (output / 'adapter_model.safetensors').write_bytes(b'existing')
    with pytest.raises(ValueError):
        pilot.ensure_empty_dir(output)


def test_prompt_profile_defaults_to_base_and_tuned_is_compact(monkeypatch):
    from src.server import bank_generation as bg
    request = bg.GenerationRequest(kind='numeric', specialization='backend', grade='junior',
                                   skills=['sql'], brief='Нужно задание про COUNT и NULL в SQLite.')
    monkeypatch.delenv('FSP_LLM_PROMPT_PROFILE', raising=False)
    system, user = bg.request_messages(request)
    assert system == bg.GENERATION_SYSTEM_PROMPT and 'format_example' in user
    monkeypatch.setenv('FSP_LLM_PROMPT_PROFILE', 'tuned')
    system, user = bg.request_messages(request)
    assert system == bg.TUNED_SYSTEM_PROMPT and 'format_example' not in user
    assert len(bg.TUNED_SYSTEM_PROMPT) < len(bg.SYSTEM_PROMPT) // 3


def test_solution_precedes_key_and_is_not_kept_in_the_draft():
    for kind, last in [('single_choice', 'options'), ('numeric', 'unit'), ('open_response', 'rubric')]:
        keys = list(generation.task_json_schema(kind, ['http'])['properties'])
        assert keys.index('solution') < keys.index(last) and keys[:5] == ['id', 'type', 'title', 'prompt', 'skills']
    result = generation.generate_task(REQUEST, MODEL, FixedProvider(json.dumps(CHOICE, ensure_ascii=False)))
    assert 'solution' not in result.task.model_dump()
    with pytest.raises(generation.GenerationRejected):
        generation.generate_task(REQUEST, MODEL, FixedProvider(json.dumps({**CHOICE, 'solution': 'коротко'})))


def test_option_letters_and_answer_hints_are_removed():
    dirty = {**CHOICE, 'prompt': 'Какой статус обозначает успешный GET запрос к существующему ресурсу? Варианты ниже — возможные ответы. Варианты ответов:',
             'options': [{'text': 'A. 200 OK', 'correct': True}, {'text': 'B) 404 Not Found', 'correct': False},
                         {'text': 'C: 500 Internal Server Error', 'correct': False}]}
    task = generation.generate_task(REQUEST, MODEL, FixedProvider(json.dumps(dirty, ensure_ascii=False))).task
    assert task.prompt == 'Какой статус обозначает успешный GET запрос к существующему ресурсу?'
    assert sorted(o.text for o in task.options) == ['200 OK', '404 Not Found', '500 Internal Server Error']



def model_http_error(status, payload):
    request = httpx.Request('POST', 'http://model.test/v1/chat/completions')
    response = httpx.Response(status, request=request, json=payload)
    return httpx.HTTPStatusError('local model error', request=request, response=response)


class FlakyProvider(FixedProvider):
    def __init__(self, failures, output):
        super().__init__(output)
        self.failures = list(failures)

    def complete_structured(self, system, user, schema, max_tokens=768, temperature=0.2):
        self.calls.append(user)
        if len(self.calls) <= len(self.failures):
            raise self.failures[len(self.calls) - 1]
        return self.output


def test_one_retry_with_changed_prompt_after_schema_refusal():
    refusal = model_http_error(502, {'detail': {'code': 'schema_rejected'}})
    provider = FlakyProvider([refusal], json.dumps(CHOICE, ensure_ascii=False))
    result = generation.generate_task(REQUEST, MODEL, provider)
    assert result.task.title == CHOICE['title'] and len(provider.calls) == 2
    assert provider.calls[1] != provider.calls[0] and 'Повтор' in provider.calls[1]


def test_second_machine_schema_refusal_is_rejected():
    failures = [model_http_error(502, {'detail': {'code': 'schema_rejected'}}) for _ in range(2)]
    provider = FlakyProvider(failures, json.dumps(CHOICE))
    with pytest.raises(generation.GenerationRejected):
        generation.generate_task(REQUEST, MODEL, provider)
    assert len(provider.calls) == 2


@pytest.mark.parametrize('error', [
    model_http_error(502, {'detail': {'code': 'runtime_unavailable'}}),
    model_http_error(502, {'detail': {'code': 'generation_incomplete'}}),
    model_http_error(422, {'detail': {'code': 'input_rejected'}}),
    model_http_error(502, {'detail': {'code': ['schema_rejected']}}),
    model_http_error(502, {'detail': {'code': 'schema_rejected', 'unexpected': True}}),
    ConnectionError('нет связи'),
])
def test_runtime_context_and_untrusted_machine_errors_are_not_retried(error):
    provider = FixedProvider(error=error)
    with pytest.raises(generation.GenerationUnavailable):
        generation.generate_task(REQUEST, MODEL, provider)
    assert len(provider.calls) == 1

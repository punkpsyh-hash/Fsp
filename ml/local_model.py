"""Изолированный локальный сервер черновиков; веса берутся только из сверенного каталога.

Запускать в GPU Docker с read-only root, D-backed model mount и приватным портом.
Этот модуль не исполняет содержимое заданий и не пишет запросы/ответы в журналы.
"""
from contextlib import asynccontextmanager
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import re
import secrets
from threading import Lock
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from src.server.bank_generation import GenerationRejected, _checked_generated_shape, task_generation_schema
from src.server.bank_review_ai import review_schema

MODEL_ID = 'Qwen/Qwen3-4B-Instruct-2507'
MODEL_REVISION = 'cdbee75f17c01a7cc42f958dc650907174af0554'
MAX_BODY_BYTES = 16000
MAX_SCHEMA_BYTES = 6000
MAX_INPUT_TOKENS = 3072
MAX_CONTEXT_TOKENS = 4096
MAX_OUTPUT_TOKENS = 1280
MAX_GENERATION_SECONDS = 120
WARMUP_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['status'],
    # LMFE 0.11.3 обрабатывает boolean const как строку и падает в startswith.
    # Одно строковое enum-значение поддерживается декодером и проверяется ниже.
    'properties': {'status': {'type': 'string', 'enum': ['ready']}},
}


class GenerationIncomplete(RuntimeError):
    """Generation stopped before a complete response was produced."""


class LocalSchemaRejected(RuntimeError):
    """The local model produced a complete response outside the requested schema."""


class BodyLimitMiddleware:
    """Ограничить фактические байты до JSON/Pydantic, включая chunked body."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('path') != '/v1/chat/completions' or scope.get('method') != 'POST':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        declared = headers.get(b'content-length')
        if declared is not None:
            try:
                size = int(declared)
            except ValueError:
                return await JSONResponse({'detail': 'Некорректная длина запроса'}, status_code=400)(scope, receive, send)
            if size > MAX_BODY_BYTES:
                return await JSONResponse({'detail': 'Запрос превышает лимит'}, status_code=413)(scope, receive, send)
        body = bytearray()
        for _ in range(64):
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > MAX_BODY_BYTES:
                return await JSONResponse({'detail': 'Запрос превышает лимит'}, status_code=413)(scope, receive, send)
            if not message.get('more_body', False):
                break
        else:
            return await JSONResponse({'detail': 'Слишком много частей запроса'}, status_code=413)(scope, receive, send)
        first = True

        async def replay():
            nonlocal first
            if first:
                first = False
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()

        return await self.app(scope, replay, send)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Message(StrictModel):
    role: Literal['system', 'user']
    content: str = Field(min_length=1, max_length=4096)


class JsonSchemaFormat(StrictModel):
    name: Literal['task_draft']
    strict: Literal[True]
    json_schema: dict = Field(alias='schema')


class ResponseFormat(StrictModel):
    type: Literal['json_schema']
    json_schema: JsonSchemaFormat


class ChatRequest(StrictModel):
    model: Literal[MODEL_ID]
    messages: list[Message] = Field(min_length=2, max_length=2)
    response_format: ResponseFormat
    max_tokens: int = Field(ge=1, le=MAX_OUTPUT_TOKENS)
    temperature: float = Field(ge=0, le=0.5)

    @model_validator(mode='after')
    def roles_in_order(self):
        if [message.role for message in self.messages] != ['system', 'user']:
            raise ValueError('Ожидаются system и user в этом порядке')
        return self


def verify_manifest(model_path: Path, manifest_path: Path) -> dict:
    """Проверить SHA-256 каждого файла и неизменный commit базовой модели."""
    if not model_path.is_dir() or model_path.is_symlink():
        raise ValueError('Каталог модели отсутствует или является ссылкой')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if set(manifest) != {'model_id', 'revision', 'files'} or manifest['model_id'] != MODEL_ID:
        raise ValueError('Неверный manifest модели')
    if manifest['revision'] != MODEL_REVISION:
        raise ValueError('Manifest должен указывать закреплённый commit модели')
    files = manifest['files']
    if not isinstance(files, dict) or not 3 <= len(files) <= 100:
        raise ValueError('Manifest не содержит полного списка файлов')
    actual = {}
    for path in model_path.rglob('*'):
        if path.is_symlink():
            raise ValueError('Ссылки в каталоге модели запрещены')
        if path.is_file():
            actual[path.relative_to(model_path).as_posix()] = path
    if set(actual) != set(files) or 'config.json' not in files or not any(
            name.endswith('.safetensors') for name in files):
        raise ValueError('Список файлов модели не совпадает с manifest')
    for name, expected in files.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9._/-]+', name) or '..' in Path(name).parts:
            raise ValueError('Недопустимое имя файла в manifest')
        if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ValueError('Недопустимый SHA-256 в manifest')
        digest = sha256()
        with actual[name].open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError('SHA-256 файла модели не совпадает с manifest')
    return manifest


def verify_adapter(adapter_path: Path, manifest_path: Path) -> dict:
    """Сверить LoRA-адаптер по SHA-256 и по закреплённой базовой модели."""
    if not adapter_path.is_dir() or adapter_path.is_symlink():
        raise ValueError('Каталог адаптера отсутствует или является ссылкой')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if set(manifest) != {'adapter_id', 'base_model_id', 'base_revision', 'files'}:
        raise ValueError('Неверный manifest адаптера')
    if manifest['base_model_id'] != MODEL_ID or manifest['base_revision'] != MODEL_REVISION:
        raise ValueError('Адаптер обучен не на закреплённой базовой модели')
    files = manifest['files']
    if set(files) != {'adapter_config.json', 'adapter_model.safetensors'}:
        raise ValueError('Манифест адаптера должен перечислять adapter_config.json и adapter_model.safetensors')
    for name, expected in files.items():
        path = adapter_path / name
        if path.is_symlink() or not path.is_file() or not re.fullmatch(r'[0-9a-f]{64}', str(expected)):
            raise ValueError('Файл адаптера недоступен либо SHA-256 некорректен')
        digest = sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError('SHA-256 файла адаптера не совпадает с manifest')
    return manifest


def checked_schema(value: dict) -> dict:
    """Допускаются только схема четырёх авторских типов из bank_generation и схема подсказки проверки."""
    if len(json.dumps(value, ensure_ascii=False).encode('utf-8')) > MAX_SCHEMA_BYTES:
        raise ValueError('Схема превышает лимит')
    if value == review_schema():
        return value
    try:
        props = value['properties']
        kind, = props['type']['enum']
        skills = props['skills']['items']['enum']
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('Недопустимая схема задания') from error
    if not isinstance(kind, str) or not isinstance(skills, list) or not all(
            isinstance(skill, str) for skill in skills):
        raise ValueError('Недопустимый список навыков')
    try:
        expected = task_generation_schema(kind, skills)
    except ValueError as error:
        raise ValueError('Неподдерживаемый тип или навыки') from error
    if value != expected:
        raise ValueError('Разрешена только схема авторского черновика')
    return expected


def verify_cuda_placement(model) -> None:
    """Отклонить не-квантованную модель и любой offload на CPU или диск."""
    if not getattr(model, 'is_loaded_in_4bit', False):
        raise RuntimeError('Модель не загружена в 4-битном режиме')
    device_map = getattr(model, 'hf_device_map', None)
    if not isinstance(device_map, dict) or not device_map or any(
            str(device) not in {'0', 'cuda:0'} for device in device_map.values()):
        raise RuntimeError('Модель размещена вне CUDA:0')
    if any(parameter.device.type != 'cuda' or parameter.device.index not in (None, 0)
           for parameter in model.parameters()):
        raise RuntimeError('Параметры модели размещены вне CUDA:0')


class LocalRuntime:
    def __init__(self, model_path: Path, manifest_path: Path,
                 adapter_path: Path | None = None, adapter_manifest_path: Path | None = None):
        self.manifest = verify_manifest(model_path, manifest_path)
        self.adapter = None
        if adapter_path is not None:
            if adapter_manifest_path is None:
                raise ValueError('Для адаптера нужен manifest')
            self.adapter = verify_adapter(adapter_path, adapter_manifest_path)
        # LMFE может писать весь prompt в root logger при внутреннем сбое.
        logging.getLogger().addFilter(_NoPromptLog())
        # Большие зависимости загружаются только внутри отдельного GPU-сервиса.
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA для локальной модели недоступна')
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(model_path), local_files_only=True, trust_remote_code=False)
        quantization = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type='nf4',
            bnb_4bit_use_double_quant=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            str(model_path), local_files_only=True, trust_remote_code=False,
            use_safetensors=True, quantization_config=quantization,
            device_map={'': 0}, dtype=torch.float16).eval()
        verify_cuda_placement(self.model)
        if self.adapter is not None:
            from peft import PeftModel
            self.model = PeftModel.from_pretrained(
                self.model, str(adapter_path), is_trainable=False, local_files_only=True).eval()
        from lmformatenforcer.integrations.transformers import build_token_enforcer_tokenizer_data
        from lmformatenforcer.tokenenforcer import TokenEnforcerTokenizerData
        data = build_token_enforcer_tokenizer_data(self.tokenizer)
        # В LMFE 0.11.3 control chars проходят и через алфавит, и через
        # ускоренный кэш свободной строки. Перестраиваем оба из безопасных
        # токенов: JSON будет компактным; экранированные \\n/\\t допустимы.
        safe_tokens = [entry for entry in data.regular_tokens
                       if all(ord(char) >= 32 for char in entry[1])]
        self.tokenizer_data = TokenEnforcerTokenizerData(
            safe_tokens,data.decoder,data.eos_token_id,data.use_bitmask,data.vocab_size)

    def warmup(self) -> None:
        """Прогреть CUDA/LMFE и подтвердить минимальный полный ответ до readiness."""
        content = self.complete([
            Message(role='system', content='Верни только JSON по заданной схеме.'),
            Message(role='user', content='Подтверди готовность.'),
        ], WARMUP_SCHEMA, 24)
        if json.loads(content) != {'status': 'ready'}:
            raise LocalSchemaRejected('Прогрев не подтвердил готовность')

    def complete(self, messages: list[Message], schema: dict, max_tokens: int) -> str:
        from lmformatenforcer import JsonSchemaParser
        from lmformatenforcer.characterlevelparser import CharacterLevelParserConfig
        from lmformatenforcer.integrations.transformers import build_transformers_prefix_allowed_tokens_fn

        tokens = self.tokenizer.apply_chat_template(
            [message.model_dump() for message in messages], tokenize=True,
            add_generation_prompt=True, return_tensors='pt')
        input_length = tokens.shape[-1]
        if input_length > MAX_INPUT_TOKENS or input_length + max_tokens > MAX_CONTEXT_TOKENS:
            raise ValueError('Контекст модели превышает лимит')
        # JsonSchemaParser запоминает alphabet_without_quotes при создании;
        # поздняя настройка TokenEnforcer не обновляет этот кэш (minLength).
        parser = JsonSchemaParser(schema,config=CharacterLevelParserConfig(
            alphabet=self.tokenizer_data.tokenizer_alphabet))
        prefix = build_transformers_prefix_allowed_tokens_fn(self.tokenizer_data,parser)
        with self.torch.inference_mode():
            output = self.model.generate(
                tokens.to('cuda'), attention_mask=self.torch.ones_like(tokens,device='cuda'),
                do_sample=False, max_new_tokens=max_tokens,
                max_time=MAX_GENERATION_SECONDS, prefix_allowed_tokens_fn=prefix,
                # Qwen config также считает endoftext концом ответа. LMFE
                # считает EOS только tokenizer.eos_token_id: другой special
                # token может попасть внутрь JSON-строки и оборвать ответ.
                eos_token_id=self.tokenizer.eos_token_id,
                bad_words_ids=[[token] for token in self.tokenizer.all_special_ids
                               if token != self.tokenizer.eos_token_id],
                pad_token_id=self.tokenizer.eos_token_id)
        generated = output[0][input_length:]
        if len(generated) >= max_tokens or not len(generated) or generated[-1].item() != self.tokenizer.eos_token_id:
            raise GenerationIncomplete('Генерация остановлена до полного ответа')
        text = self.tokenizer.decode(generated, skip_special_tokens=True).strip()
        try:
            raw = json.loads(text)
        except ValueError as error:
            raise LocalSchemaRejected('Модель не вернула JSON') from error
        if not isinstance(raw, dict):
            raise LocalSchemaRejected('Модель не вернула объект JSON')
        return text


class _NoPromptLog(logging.Filter):
    def filter(self, record):
        return not (isinstance(record.msg, str) and record.msg.startswith('Unknown LMFormatEnforcer Problem. Prefix:'))


runtime: LocalRuntime | None = None
active_request = Lock()


def _ready_report(current: LocalRuntime) -> dict:
    result = {'status': 'ready', 'model': MODEL_ID, 'revision': current.manifest['revision']}
    if getattr(current, 'adapter', None):
        result['adapter'] = {'id': current.adapter['adapter_id'], 'files': current.adapter['files']}
    if hasattr(current, 'torch'):
        result['gpu'] = {'allocated_bytes': current.torch.cuda.memory_allocated(),
                         'peak_allocated_bytes': current.torch.cuda.max_memory_allocated(),
                         'total_bytes': current.torch.cuda.get_device_properties(0).total_memory}
        result['quantization'] = {'bits': 4, 'type': 'nf4', 'double_quant': True,
                                  'placement': 'cuda:0'}
    return result


def _write_startup_report(report: dict) -> None:
    target = os.environ.get('FSP_LOCAL_MODEL_STARTUP_REPORT')
    if not target:
        return
    path = Path(target)
    if not path.is_absolute() or path.name != 'startup.json':
        raise RuntimeError('Недопустимый путь отчёта запуска')
    payload = json.dumps(report, ensure_ascii=False, separators=(',', ':')).encode('utf-8') + b'\n'
    if len(payload) > 8192:
        raise RuntimeError('Отчёт запуска превышает лимит')
    temporary = path.with_name('.startup-' + secrets.token_hex(8) + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as destination:
            destination.write(payload)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global runtime
    try:
        model_path = Path(os.environ['FSP_LOCAL_MODEL_PATH'])
        manifest_path = Path(os.environ['FSP_LOCAL_MODEL_MANIFEST'])
        adapter = os.environ.get('FSP_LOCAL_ADAPTER_PATH')
        runtime = LocalRuntime(model_path, manifest_path,
                               Path(adapter) if adapter else None,
                               Path(os.environ['FSP_LOCAL_ADAPTER_MANIFEST']) if adapter else None)
        if os.environ.get('FSP_LOCAL_MODEL_WARMUP', '1') != '0':
            runtime.warmup()
        ready_report = _ready_report(runtime)
    except Exception as error:
        runtime = None
        error_type = type(error).__name__
        if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', error_type):
            error_type = 'Exception'
        _write_startup_report({'status': 'error', 'model': MODEL_ID,
                               'revision': MODEL_REVISION, 'error_type': error_type})
        raise
    try:
        _write_startup_report(ready_report)
        yield
    finally:
        runtime = None


app = FastAPI(title='FSP local draft model', docs_url=None, redoc_url=None,
              openapi_url=None, lifespan=lifespan)
app.add_middleware(BodyLimitMiddleware)


@app.get('/health')
def health():
    if runtime is None:
        raise HTTPException(503, 'Модель не загружена')
    return _ready_report(runtime)


@app.post('/v1/chat/completions')
async def chat(body: ChatRequest, authorization: str | None = Header(default=None)):
    token = os.environ.get('FSP_LOCAL_MODEL_API_KEY', '')
    if token and not secrets.compare_digest(authorization or '', 'Bearer ' + token):
        raise HTTPException(401, 'Требуется ключ локальной модели')
    if runtime is None:
        raise HTTPException(503, 'Модель не загружена')
    try:
        schema = checked_schema(body.response_format.json_schema.json_schema)
    except ValueError as error:
        raise HTTPException(422, {'code': 'input_rejected'}) from error
    if not active_request.acquire(blocking=False):
        raise HTTPException(429, 'Модель занята')
    try:
        try:
            content = await run_in_threadpool(runtime.complete, body.messages, schema, body.max_tokens)
            parsed = json.loads(content)
            if schema == review_schema():
                if not isinstance(parsed, dict) or set(parsed) != {'analysis', 'score', 'feedback'}:
                    raise GenerationRejected('Подсказка не соблюла схему')
            else:
                _checked_generated_shape(parsed, schema['properties']['type']['enum'][0],
                                         schema['properties']['skills']['items']['enum'], serving=True)
        except (json.JSONDecodeError, LocalSchemaRejected) as error:
            raise HTTPException(502, {'code': 'schema_rejected'}) from error
        except GenerationIncomplete as error:
            raise HTTPException(502, {'code': 'generation_incomplete'}) from error
        except ValueError as error:
            raise HTTPException(422, {'code': 'input_rejected'}) from error
        except GenerationRejected as error:
            raise HTTPException(502, {'code': 'schema_rejected'}) from error
        except Exception as error:
            raise HTTPException(502, {'code': 'runtime_unavailable'}) from error
    finally:
        active_request.release()
    return {'object': 'chat.completion', 'model': MODEL_ID, 'choices': [
        {'index': 0, 'message': {'role': 'assistant', 'content': content}, 'finish_reason': 'stop'}]}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8001, access_log=False, log_level='warning')

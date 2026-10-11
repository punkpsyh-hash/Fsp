"""Малый воспроизводимый LoRA-пилот на авторских примерах банка.

Команды выполняются только в GPU-контейнере с каталогами моделей/данных на D.
`prepare` и `eval` не объявляют экспертной калибровки или пригодности модели.
"""
import argparse
import hashlib
import json
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = 'Qwen/Qwen2.5-0.5B-Instruct'
MODEL_REVISION = '7ae557604adf67be50417f59c2c2f167def9a775'
SEED = 20261009
STEPS = 20

# Три конкурсные темы зафиксированы как закрытая контрольная группа до обучения.
# Все четыре простые темы из другого банка идут в train. Варианты семейства
# нельзя разносить по двум группам, даже если позднее примеров станет больше.
HOLDOUT_FAMILIES = {
    'http-idempotency-scope-and-replay',
    'privacy-owner-scoped-grants-and-revocation',
    'atomic-read-modify-write-idempotent-reservation',
}
BRIEFS = {
    'http-choice': 'Создайте вопрос о статусе успешного GET-запроса и трёх вариантах ответа.',
    'sql-choice': 'Создайте вопрос о командах SQL для чтения и изменения строк.',
    'time-number': 'Создайте числовую задачу на перевод двух минут в секунды.',
    'retry-open': 'Попросите описать защиту API от повторного создания приглашения.',
    'idempotency-contract': 'Проверьте идемпотентность HTTP-операции при повторном запросе.',
    'contact-revoke-model': 'Проверьте адресное разрешение на контакт и его отзыв.',
    'atomic-quota-reservation': 'Попросите объяснить атомарное резервирование ограниченного ресурса.',
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def ensure_empty_dir(path):
    """Пустой заранее созданный каталог допустим; чужой результат не перезаписываем."""
    path = Path(path)
    if path.exists():
        if not path.is_dir() or any(path.iterdir()):
            raise ValueError('Каталог эксперимента уже содержит файлы; выберите новый')
    else:
        path.mkdir(parents=True, exist_ok=False)


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def write_rows(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(canonical(row) + '\n' for row in values), encoding='utf-8')


def prepare(args):
    from src.server.bank_schemas import Task, publication_errors

    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Каталог splits уже содержит файлы; новый эксперимент требует нового каталога')
    prepared = []
    sources = []
    for filename in ('bank-all-types.json', 'bank-contest.json'):
        path = ROOT / 'requirements' / 'examples' / filename
        document = json.loads(path.read_text(encoding='utf-8'))
        sources.append({'path': str(path.relative_to(ROOT)).replace('\\', '/'), 'sha256': digest(path),
                        'origin': 'Авторские синтетические задания проекта; экспертная калибровка не проводилась',
                        'rights_basis': 'Локальный исследовательский пилот на материалах владельца проекта'})
        for item in document['tasks']:
            if item['type'] == 'code':
                continue  # Генерация исполняемого кода в первом срезе запрещена.
            task = Task.model_validate(item).model_dump(mode='json', exclude_defaults=True, exclude_none=True)
            task['id'] = 'suggestion'  # Совпадает с форматом запроса; исходный ID хранится отдельно.
            if task['type'] == 'open_response' and ('0:' not in task['rubric'] or '100:' not in task['rubric']):
                # Явная производная нормализация: оригинальная рубрика в банке не меняется.
                task['rubric'] = ('0: критерии не выполнены. 100: все критерии выполнены. '
                                  + task['rubric'])
            if publication_errors({'tasks': [Task.model_validate(item).model_dump(mode='json')]}):
                raise ValueError(f'Исходное задание не проходит правила публикации: {item["id"]}')
            family = item.get('family') or 'all-types-' + item['id']
            row = {'id': item['id'], 'family': family, 'kind': item['type'],
                             'specialization': document['specialization'], 'grade': document['grade'],
                             'skills': item['skills'], 'brief': BRIEFS[item['id']], 'target': task,
                             'provenance': filename, 'review_status': 'author_example_not_expert_curated'}
            from src.server.bank_generation import GenerationRequest, _checked_task
            _checked_task(task, GenerationRequest.model_validate({
                'kind': row['kind'], 'specialization': row['specialization'], 'grade': row['grade'],
                'skills': row['skills'], 'brief': row['brief']}))
            prepared.append(row)
    if set(BRIEFS) != {row['id'] for row in prepared}:
        raise ValueError('Каждому неисполняемому примеру нужен явный учебный запрос')
    train = [row for row in prepared if row['family'] not in HOLDOUT_FAMILIES]
    holdout = [row for row in prepared if row['family'] in HOLDOUT_FAMILIES]
    if len(train) != 4 or len(holdout) != 3:
        raise ValueError('Изменился исходный авторский банк; пересмотрите split до обучения')
    if {r['family'] for r in train} & {r['family'] for r in holdout}:
        raise ValueError('Семейство попало и в train, и в holdout')
    write_rows(output / 'train.jsonl', train)
    write_rows(output / 'holdout.jsonl', holdout)
    manifest = {'protocol': 'author-example-lora-pilot-v1', 'seed': SEED,
                'model_id': MODEL_ID, 'model_revision': MODEL_REVISION,
                'sources': sources, 'train_count': len(train), 'holdout_count': len(holdout),
                'train_families': sorted({r['family'] for r in train}),
                'holdout_families': sorted({r['family'] for r in holdout}),
                'review_status': 'author_example_not_expert_curated',
                'normalization': 'target.id=suggestion; one open_response rubric gained explicit 0/100 anchors',
                'limitations': 'Только 4 обучающих и 3 контрольных задания; технический пилот, не оценка качества найма'}
    manifest['train_sha256'] = digest(output / 'train.jsonl')
    manifest['holdout_sha256'] = digest(output / 'holdout.jsonl')
    write_json(output / 'manifest.json', manifest)
    print(canonical({'output': str(output), 'train': len(train), 'holdout': len(holdout),
                     'review_status': manifest['review_status']}))


def verified_split(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['model_id'] != MODEL_ID or manifest['model_revision'] != MODEL_REVISION:
        raise ValueError('Модель эксперимента не совпадает с manifest')
    for name in ('train', 'holdout'):
        if digest(folder / f'{name}.jsonl') != manifest[f'{name}_sha256']:
            raise ValueError(f'Хеш {name} изменился после фиксации split')
    if set(manifest['train_families']) & set(manifest['holdout_families']):
        raise ValueError('Семейства train и holdout пересекаются')
    return folder, manifest


def fetch(args):
    """Явная загрузка закреплённого checkpoint; train/eval сеть не используют."""
    from huggingface_hub import snapshot_download

    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Каталог модели уже содержит файлы; проверьте его отдельно')
    snapshot_download(repo_id=MODEL_ID, revision=MODEL_REVISION, local_dir=output,
                      allow_patterns=['*.safetensors', '*.json', 'LICENSE', 'README.md',
                                      'vocab.json', 'merges.txt'], max_workers=2)
    weights = output / 'model.safetensors'
    if not weights.is_file() or not (output / 'LICENSE').is_file():
        raise FileNotFoundError('После загрузки отсутствуют веса или LICENSE')
    write_json(output / 'pilot-model-manifest.json',
               {'model_id': MODEL_ID, 'revision': MODEL_REVISION,
                'weights_sha256': digest(weights), 'license': 'Apache-2.0'})
    print(canonical({'output': str(output), 'weights_sha256': digest(weights)}))


def messages(row):
    from src.server.bank_generation import SYSTEM_PROMPT
    request = {'type': row['kind'], 'specialization': row['specialization'],
               'grade': row['grade'], 'skills': row['skills'], 'brief': row['brief']}
    return [{'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': json.dumps(request, ensure_ascii=False)}]


def load_model(model_path, adapter_path=None):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    path = Path(model_path).resolve()
    if not (path / 'config.json').is_file() or not (path / 'model.safetensors').is_file():
        raise FileNotFoundError('Нужны локальные исходные веса модели и config.json на диске D')
    manifest_path = path / 'pilot-model-manifest.json'
    if not manifest_path.is_file():
        raise FileNotFoundError('Отсутствует манифест закреплённой базовой модели')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest['model_id'] != MODEL_ID or manifest['revision'] != MODEL_REVISION or \
            manifest['weights_sha256'] != digest(path / 'model.safetensors'):
        raise ValueError('Хеш или версия базовой модели не совпадает с манифестом')
    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)
    model = AutoModelForCausalLM.from_pretrained(path, local_files_only=True,
                                                 trust_remote_code=False, torch_dtype=torch.float16)
    if adapter_path:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, str(Path(adapter_path).resolve()), is_trainable=False)
    model.to('cuda')
    return model, tokenizer


def probe(args):
    """Проверить полные длины до обучения; не обрезает данные и не загружает GPU."""
    from transformers import AutoTokenizer

    folder, manifest = verified_split(args.splits)
    model_path = Path(args.model).resolve()
    model_manifest = json.loads((model_path / 'pilot-model-manifest.json').read_text(encoding='utf-8'))
    if model_manifest['revision'] != MODEL_REVISION or model_manifest['weights_sha256'] != digest(model_path / 'model.safetensors'):
        raise ValueError('Манифест базовой модели не совпадает с весами')
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True, trust_remote_code=False)
    sizes = []
    for split in ('train', 'holdout'):
        for row in rows(folder / f'{split}.jsonl'):
            prompt = tokenizer.apply_chat_template(messages(row), tokenize=True, add_generation_prompt=True)
            target = tokenizer(canonical(row['target']), add_special_tokens=False)['input_ids'] + [tokenizer.eos_token_id]
            sizes.append({'split': split, 'id': row['id'], 'prompt_tokens': len(prompt),
                          'target_tokens': len(target), 'total_tokens': len(prompt) + len(target)})
    over = [item['id'] for item in sizes if item['split'] == 'train' and item['total_tokens'] > args.max_length]
    report = {'model_revision': MODEL_REVISION, 'train_sha256': manifest['train_sha256'],
              'holdout_sha256': manifest['holdout_sha256'], 'max_length': args.max_length,
              'sizes': sizes, 'train_over_budget': over, 'truncation': False}
    out = Path(args.output).resolve()
    if out.exists():
        raise ValueError('Файл проверки длины уже существует')
    write_json(out, report)
    print(canonical({'output': str(out), 'train_over_budget': over,
                     'max_train_tokens': max(x['total_tokens'] for x in sizes if x['split'] == 'train')}))
    if over:
        raise ValueError('Обучающие эталоны превышают бюджет токенов; проверьте отчёт и выберите длину до обучения')


def train(args):
    import torch
    from peft import LoraConfig, get_peft_model

    folder, manifest = verified_split(args.splits)
    budget = json.loads(Path(args.budget_report).read_text(encoding='utf-8'))
    if budget['train_sha256'] != manifest['train_sha256'] or budget['holdout_sha256'] != manifest['holdout_sha256'] or \
            budget['max_length'] != args.max_length or budget['train_over_budget']:
        raise ValueError('Нет подходящей проверки полной длины до обучения')
    baseline = json.loads(Path(args.base_report).read_text(encoding='utf-8'))
    if baseline['model_revision'] != MODEL_REVISION or baseline['holdout_sha256'] != manifest['holdout_sha256'] or \
            baseline['adapter_sha256'] is not None:
        raise ValueError('До обучения нужен результат исходной модели на закрытом holdout')
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA недоступна в контейнере')
    free, total = torch.cuda.mem_get_info()
    if free < 3 * 1024**3:
        raise RuntimeError('Для пилота требуется минимум 3 GiB свободной VRAM до загрузки модели')
    output = Path(args.output).resolve()
    ensure_empty_dir(output)
    torch.manual_seed(SEED)
    random.seed(SEED)
    model, tokenizer = load_model(args.model)
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model.config.use_cache = False
    model = get_peft_model(model, LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05,
                                           target_modules=['q_proj', 'v_proj'], bias='none',
                                           task_type='CAUSAL_LM'))
    model.train()
    examples = []
    for row in rows(folder / 'train.jsonl'):
        prompt_ids = tokenizer.apply_chat_template(messages(row), tokenize=True, add_generation_prompt=True)
        target_ids = tokenizer(canonical(row['target']), add_special_tokens=False)['input_ids'] + [tokenizer.eos_token_id]
        if len(prompt_ids) + len(target_ids) > args.max_length:
            raise ValueError(f'Задание {row["id"]} не помещается в {args.max_length} токенов; данные не обрезаются')
        input_ids = prompt_ids + target_ids
        labels = [-100] * len(prompt_ids) + target_ids
        examples.append((torch.tensor([input_ids], device='cuda'), torch.tensor([labels], device='cuda')))
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=2e-4)
    scaler = torch.amp.GradScaler('cuda')
    torch.cuda.reset_peak_memory_stats()
    losses = []
    for step in range(STEPS):
        input_ids, labels = examples[step % len(examples)]
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast('cuda', dtype=torch.float16):
            loss = model(input_ids=input_ids, labels=labels).loss
        if not torch.isfinite(loss):
            raise RuntimeError('Потеря стала NaN/Inf; адаптер не сохраняется')
        scaler.scale(loss).backward()
        scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_((p for p in model.parameters() if p.requires_grad), 1.0)
        scaler.step(optimizer)
        scaler.update()
        losses.append(round(float(loss.detach()), 6))
    ensure_empty_dir(output)
    model.save_pretrained(output, safe_serialization=True)
    report = {'status': 'trained_pilot_adapter', 'model_id': MODEL_ID, 'model_revision': MODEL_REVISION,
              'base_weights_sha256': digest(Path(args.model) / 'model.safetensors'),
              'train_sha256': manifest['train_sha256'], 'holdout_sha256': manifest['holdout_sha256'],
              'seed': SEED, 'steps': STEPS, 'max_length': args.max_length, 'batch_size': 1,
              'optimizer': 'AdamW', 'learning_rate': 0.0002, 'lora_r': 8, 'lora_alpha': 16,
              'lora_dropout': 0.05, 'target_modules': ['q_proj', 'v_proj'],
              'gpu': torch.cuda.get_device_name(), 'vram_total_bytes': total,
              'peak_allocated_bytes': torch.cuda.max_memory_allocated(),
              'losses': losses, 'adapter_sha256': digest(output / 'adapter_model.safetensors'),
              'limitations': manifest['limitations']}
    write_json(output / 'pilot-report.json', report)
    print(canonical({'output': str(output), 'steps': STEPS,
                     'final_loss': losses[-1], 'peak_allocated_bytes': report['peak_allocated_bytes']}))


def evaluate(args):
    import torch
    from src.server import bank_generation as generation

    folder, manifest = verified_split(args.splits)
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA недоступна в контейнере')
    if args.adapter:
        report = json.loads((Path(args.adapter) / 'pilot-report.json').read_text(encoding='utf-8'))
        if report['train_sha256'] != manifest['train_sha256'] or report['holdout_sha256'] != manifest['holdout_sha256']:
            raise ValueError('Адаптер обучен на другом split')
        if digest(Path(args.adapter) / 'adapter_model.safetensors') != report['adapter_sha256']:
            raise ValueError('Хеш адаптера изменился')
    model, tokenizer = load_model(args.model, args.adapter)
    model.eval()
    torch.manual_seed(SEED)
    results = []
    for row in rows(folder / 'holdout.jsonl'):
        prompt_ids = tokenizer.apply_chat_template(messages(row), tokenize=True, add_generation_prompt=True)
        input_ids = torch.tensor([prompt_ids], device='cuda')
        with torch.inference_mode():
            generated = model.generate(input_ids=input_ids, max_new_tokens=512, do_sample=False,
                                       pad_token_id=tokenizer.eos_token_id)
        answer = tokenizer.decode(generated[0, len(prompt_ids):], skip_special_tokens=True).strip()
        status = {'valid_json': False, 'task_schema': False, 'publication_fields': False,
                  'kind_and_skills': False, 'key_or_rubric_consistency': False}
        try:
            payload = json.loads(answer)
            status['valid_json'] = isinstance(payload, dict)
            from src.server.bank_schemas import Task, publication_errors
            task = Task.model_validate(payload)
            status['task_schema'] = True
            status['publication_fields'] = not publication_errors({'tasks': [task.model_dump(mode='json')]})
            request = generation.GenerationRequest.model_validate({
                'kind': row['kind'], 'specialization': row['specialization'], 'grade': row['grade'],
                'skills': row['skills'], 'brief': row['brief']})
            status['kind_and_skills'] = task.type == request.kind and task.skills == request.skills
            generation._checked_task(payload, request)
            status['key_or_rubric_consistency'] = True
        except (ValueError, TypeError, generation.GenerationRejected):
            pass
        results.append({'id': row['id'], 'family': row['family'], 'checks': status,
                        'raw_output': answer})  # Только локальный игнорируемый каталог runs/.
    metrics = {key: sum(int(item['checks'][key]) for item in results)
               for key in results[0]['checks']}
    result = {'model_id': MODEL_ID, 'model_revision': MODEL_REVISION,
              'adapter_sha256': digest(Path(args.adapter) / 'adapter_model.safetensors') if args.adapter else None,
              'holdout_sha256': manifest['holdout_sha256'], 'count': len(results), 'metrics': metrics,
              'decode': {'max_new_tokens': 512, 'do_sample': False}, 'items': results,
              'limitations': 'Автоматические проверки не измеряют верность ответа, однозначность или сложность'}
    out = Path(args.output).resolve()
    if out.exists():
        raise ValueError('Файл оценки уже существует; не перезаписывайте результат')
    write_json(out, result)
    print(canonical({'output': str(out), 'count': len(results), 'metrics': metrics}))


def compare(args):
    base = json.loads(Path(args.base).read_text(encoding='utf-8'))
    adapted = json.loads(Path(args.adapted).read_text(encoding='utf-8'))
    for field in ('model_id', 'model_revision', 'holdout_sha256', 'count', 'decode'):
        if base[field] != adapted[field]:
            raise ValueError(f'Несопоставимые результаты: {field}')
    if base['adapter_sha256'] is not None or not adapted['adapter_sha256']:
        raise ValueError('Ожидаются результат базовой модели и результат адаптера')
    report = {'count': base['count'], 'holdout_sha256': base['holdout_sha256'],
              'base': base['metrics'], 'adapter': adapted['metrics'],
              'delta': {key: adapted['metrics'][key] - value for key, value in base['metrics'].items()},
              'limitations': 'Три авторских контрольных задания; без экспертной проверки нельзя заявлять качество'}
    out = Path(args.output).resolve()
    if out.exists():
        raise ValueError('Файл сравнения уже существует')
    write_json(out, report)
    print(canonical(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--output', required=True); p.set_defaults(run=prepare)
    p = sub.add_parser('fetch'); p.add_argument('--output', required=True); p.set_defaults(run=fetch)
    p = sub.add_parser('probe'); p.add_argument('--splits', required=True); p.add_argument('--model', required=True)
    p.add_argument('--max-length', type=int, choices=(512, 768, 1024), default=512)
    p.add_argument('--output', required=True); p.set_defaults(run=probe)
    p = sub.add_parser('train'); p.add_argument('--splits', required=True); p.add_argument('--model', required=True)
    p.add_argument('--max-length', type=int, choices=(512, 768, 1024), default=512)
    p.add_argument('--budget-report', required=True)
    p.add_argument('--base-report', required=True)
    p.add_argument('--output', required=True); p.set_defaults(run=train)
    p = sub.add_parser('eval'); p.add_argument('--splits', required=True); p.add_argument('--model', required=True)
    p.add_argument('--adapter'); p.add_argument('--output', required=True); p.set_defaults(run=evaluate)
    p = sub.add_parser('compare'); p.add_argument('--base', required=True); p.add_argument('--adapted', required=True)
    p.add_argument('--output', required=True); p.set_defaults(run=compare)
    args = parser.parse_args()
    args.run(args)


if __name__ == '__main__':
    main()

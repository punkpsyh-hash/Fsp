"""QLoRA-дообучение Qwen3-4B-Instruct-2507 на корпусе заданий (NF4 + LoRA, CUDA:0).

Запуск только в GPU-контейнере без сети (ml/dr.sh --gpu). Лосс считается только по ответу
модели; формат сообщений тот же, что у продукта (system + user -> компактный JSON).
Контрольные семейства (heldout) и закрытая проверка обучением не читаются.
"""
import argparse
import hashlib
import json
import math
import random
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_rows(path, limit=None):
    rows = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
    return rows[:limit] if limit else rows


def encode(tokenizer, row, max_len):
    prompt = tokenizer.apply_chat_template(
        [{'role': 'system', 'content': row['system']}, {'role': 'user', 'content': row['user']}],
        tokenize=False, add_generation_prompt=True)
    prompt_ids = tokenizer(prompt, add_special_tokens=False)['input_ids']
    answer_ids = tokenizer(row['completion'], add_special_tokens=False)['input_ids'] + [tokenizer.eos_token_id]
    ids = prompt_ids + answer_ids
    if len(ids) > max_len:
        return None
    return ids, [-100] * len(prompt_ids) + answer_ids


def batches(examples, micro, rng, shuffle):
    """Группировка по длине уменьшает padding; порядок групп перемешивается."""
    order = list(range(len(examples)))
    if shuffle:
        rng.shuffle(order)
        chunk = micro * 32
        order = [i for start in range(0, len(order), chunk)
                 for i in sorted(order[start:start + chunk], key=lambda k: len(examples[k][0]))]
    groups = [order[i:i + micro] for i in range(0, len(order), micro)]
    if shuffle:
        rng.shuffle(groups)
    return groups


def collate(torch, examples, indices, pad_id):
    width = max(len(examples[i][0]) for i in indices)
    ids = torch.full((len(indices), width), pad_id, dtype=torch.long)
    labels = torch.full((len(indices), width), -100, dtype=torch.long)
    mask = torch.zeros((len(indices), width), dtype=torch.long)
    for row, i in enumerate(indices):
        a, b = examples[i]
        ids[row, :len(a)] = torch.tensor(a)
        labels[row, :len(b)] = torch.tensor(b)
        mask[row, :len(a)] = 1
    return ids.to('cuda'), labels.to('cuda'), mask.to('cuda')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True)
    parser.add_argument('--train', required=True)
    parser.add_argument('--val', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--epochs', type=float, default=1.0)
    parser.add_argument('--lr', type=float, default=2e-4)
    parser.add_argument('--rank', type=int, default=32)
    parser.add_argument('--alpha', type=int, default=64)
    parser.add_argument('--micro-batch', type=int, default=2)
    parser.add_argument('--accum', type=int, default=8)
    parser.add_argument('--max-len', type=int, default=1536)
    parser.add_argument('--init-adapter', default='', help='продолжить обучение существующего LoRA-адаптера')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--max-steps', type=int, default=0)
    parser.add_argument('--eval-every', type=int, default=50)
    parser.add_argument('--seed', type=int, default=20261009)
    args = parser.parse_args()

    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    out = Path(args.output)
    if out.exists() and any(out.iterdir()):
        raise SystemExit('Каталог адаптера уже содержит файлы; выберите новый')
    out.mkdir(parents=True, exist_ok=True)
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    rng = random.Random(args.seed)

    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    train_rows = load_rows(args.train, args.limit or None)
    val_rows = load_rows(args.val, 120)
    train = [e for e in (encode(tokenizer, r, args.max_len) for r in train_rows) if e]
    val = [e for e in (encode(tokenizer, r, args.max_len) for r in val_rows) if e]
    print(json.dumps({'train': len(train), 'dropped_long': len(train_rows) - len(train), 'val': len(val),
                      'tokens_train': sum(len(e[0]) for e in train)}), flush=True)

    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4', bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(args.model, local_files_only=True, quantization_config=quant,
                                                 device_map={'': 0}, dtype=torch.bfloat16)
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
                                            gradient_checkpointing_kwargs={'use_reentrant': False})
    config = LoraConfig(r=args.rank, lora_alpha=args.alpha, lora_dropout=0.05, bias='none', task_type='CAUSAL_LM',
                        target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj'])
    if args.init_adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, args.init_adapter, is_trainable=True, local_files_only=True)
    else:
        model = get_peft_model(model, config)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print('trainable_params', trainable, flush=True)
    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.0, betas=(0.9, 0.99))

    steps_per_epoch = math.ceil(len(train) / (args.micro_batch * args.accum))
    total_steps = args.max_steps or max(1, int(steps_per_epoch * args.epochs))
    warmup = max(3, int(0.04 * total_steps))

    def lr_at(step):
        if step < warmup:
            return args.lr * (step + 1) / warmup
        progress = (step - warmup) / max(1, total_steps - warmup)
        return args.lr * (0.05 + 0.95 * 0.5 * (1 + math.cos(math.pi * progress)))

    inner = model.base_model.model

    def answer_loss(ids, labels, mask):
        """Логиты считаются только в позициях ответа: словарь 151k делает полный вывод слишком дорогим."""
        hidden = inner.model(input_ids=ids, attention_mask=mask).last_hidden_state[:, :-1]
        target = labels[:, 1:]
        pick = target != -100
        logits = inner.lm_head(hidden[pick]).float()
        loss = torch.nn.functional.cross_entropy(logits, target[pick], reduction='sum')
        return loss, int(pick.sum().item())

    def evaluate():
        model.eval()
        total, count = 0.0, 0
        with torch.no_grad():
            for group in batches(val, args.micro_batch, rng, False):
                ids, labels, mask = collate(torch, val, group, tokenizer.pad_token_id or tokenizer.eos_token_id)
                loss, n = answer_loss(ids, labels, mask)
                total += loss.item()
                count += n
        model.train()
        return total / max(1, count)

    log = []
    started = time.time()
    model.train()
    step = 0
    micro_seen = 0
    running, running_tokens = 0.0, 0
    pad = tokenizer.pad_token_id or tokenizer.eos_token_id
    epoch = 0
    done = False
    while not done:
        for group in batches(train, args.micro_batch, rng, True):
            ids, labels, mask = collate(torch, train, group, pad)
            loss_sum, n_tok = answer_loss(ids, labels, mask)
            # нормируем на токены ответа микробатча и на число накоплений
            (loss_sum / max(1, n_tok) / args.accum).backward()
            running += loss_sum.item()
            running_tokens += n_tok
            micro_seen += 1
            if micro_seen % args.accum:
                continue
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            for g in optimizer.param_groups:
                g['lr'] = lr_at(step)
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            step += 1
            record = {'step': step, 'train_loss': running / max(1, running_tokens), 'lr': lr_at(step - 1),
                      'elapsed_s': round(time.time() - started, 1),
                      'peak_vram_gb': round(torch.cuda.max_memory_allocated() / 2**30, 2)}
            running, running_tokens = 0.0, 0
            if step % args.eval_every == 0 or step == total_steps:
                record['val_loss'] = evaluate()
            log.append(record)
            if step % 5 == 0 or 'val_loss' in record:
                print(json.dumps(record), flush=True)
            if step % 100 == 0:
                model.save_pretrained(out / f'checkpoint-{step}')
            if step >= total_steps:
                done = True
                break
        epoch += 1
    model.save_pretrained(out)
    report = {
        'schema': 'fsp-qlora-report-v1', 'base_model': 'Qwen/Qwen3-4B-Instruct-2507',
        'base_revision': 'cdbee75f17c01a7cc42f958dc650907174af0554', 'args': vars(args),
        'train_sha256': digest(args.train), 'val_sha256': digest(args.val),
        'init_adapter': args.init_adapter, 'examples_train': len(train), 'examples_val': len(val), 'trainable_params': trainable,
        'steps': step, 'seconds': round(time.time() - started, 1),
        'peak_vram_gb': round(torch.cuda.max_memory_allocated() / 2**30, 2), 'log': log,
        'adapter_sha256': {p.name: digest(p) for p in sorted(out.glob('adapter_*'))},
    }
    (out / 'train-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('done', report['seconds'], 's', flush=True)


if __name__ == '__main__':
    main()

"""Сборка корпуса обучения: python -m ml.corpus.build_corpus --out ml/datasets/curated/<имя>.

Семейство = генератор либо группа утверждений. HELDOUT_FAMILIES целиком исключены из train/val
и нужны для оценки переноса на непросмотренные семейства.
"""
import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

from . import fam_algo, fam_facts, fam_facts2, fam_js, fam_py, fam_sql, fam_web
from .core import KINDS, make_example, request_for, work_from_rubric

HELDOUT_FAMILIES = {
    'sql_dml_affected', 'py_exceptions', 'js_loop_closure', 'http_cache', 'qa_coverage', 'css_specificity',
    'facts_javascript_14', 'facts_http_26', 'facts_testing_35', 'facts_python_4',
    'algo_recursion', 'sql_count_distinct', 'css_media_query',
    'facts2_http_4', 'facts2_testing_26', 'facts2_javascript_16', 'facts2_python_8',
}
DRAWS = {'computed': 55, 'facts': 16}


def all_families():
    items = []
    for module in (fam_sql, fam_py, fam_js, fam_web, fam_algo):
        for fam in module.FAMILIES:
            items.append((fam.__name__, fam, 'computed'))
    for mod in (fam_facts, fam_facts2):
        for name, fam in zip(mod.FAMILY_NAMES, mod.FAMILIES):
            items.append((name, fam, 'facts'))
    return items


def build(seed, draws_scale=1.0):
    rows = []
    stats = Counter()
    for name, fam, group in all_families():
        draws = int(DRAWS[group] * draws_scale)
        made = 0
        attempt = 0
        while made < draws and attempt < draws * 6:
            attempt += 1
            rng = random.Random(f'{seed}:{name}:{attempt}')
            grade = rng.choice(['junior', 'middle'])
            try:
                sc = fam(rng, grade)
            except (ValueError, AssertionError, IndexError, KeyError):
                stats['gen_skipped'] += 1
                continue
            ok = 0
            work = work_from_rubric(sc['tasks']['open_response'][0]) if 'open_response' in sc['tasks'] else sc.get('work')
            for kind, (task, brief) in sc['tasks'].items():
                try:
                    request = request_for(kind, sc['spec'], grade, sc['skills'], brief)
                    rows.append(make_example(name, request, task, work=work, seed=f'{seed}:{name}:{attempt}'))
                    ok += 1
                except Exception:
                    stats['val_skipped'] += 1
            made += bool(ok)
        stats[name] = made
    return rows, stats


def dedupe(rows):
    seen, out = set(), []
    for row in rows:
        key = hashlib.sha256((row['user'] + row['completion']).encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def write(path, rows):
    path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--seed', default='corpus-v1')
    parser.add_argument('--scale', type=float, default=1.0)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    rows, stats = build(args.seed, args.scale)
    rows = dedupe(rows)
    held = [r for r in rows if r['family'] in HELDOUT_FAMILIES]
    rest = [r for r in rows if r['family'] not in HELDOUT_FAMILIES]
    rng = random.Random(args.seed)
    rng.shuffle(rest)
    cut = max(50, len(rest) // 25)
    val, train = rest[:cut], rest[cut:]
    write(out / 'train.jsonl', train)
    write(out / 'val.jsonl', val)
    write(out / 'heldout-families.jsonl', held)
    manifest = {
        'schema': 'fsp-sft-corpus-v1', 'seed': args.seed, 'heldout_families': sorted(HELDOUT_FAMILIES),
        'counts': {'train': len(train), 'val': len(val), 'heldout': len(held)},
        'by_kind': dict(Counter(r['kind'] for r in train)),
        'by_family_train': dict(Counter(r['family'] for r in train)),
        'skipped': {k: v for k, v in stats.items() if k in {'gen_skipped', 'val_skipped'}},
        'provenance': 'author_generated_computed_truth_not_expert_curated',
        'files_sha256': {f: hashlib.sha256((out / f).read_bytes()).hexdigest() for f in ('train.jsonl', 'val.jsonl', 'heldout-families.jsonl')},
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: manifest[k] for k in ('counts', 'by_kind', 'skipped')}, ensure_ascii=False))


if __name__ == '__main__':
    main()

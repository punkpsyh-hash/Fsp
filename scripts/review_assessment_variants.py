"""Диагностика v4 и архивного v3; исходный протокол v3 не перезаписывается."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.server.assessment import CATALOG, evaluate, questions

# Историческая диагностика v4: смена основной формы не переименовывает её результаты.
VERSION = 'families-v4'


def transfer_case(specialization, grade, version, donor_count, target_count):
    forms = [questions(seed, grade, specialization, version) for seed in range(target_count)]
    answer_values = defaultdict(set)
    for form in forms:
        for q in form:
            answer_values[q['id']].add(q['answer'])
    scores, passed_pairs = [], []
    for donor_seed in range(donor_count):
        donor = {q['id']: q['answer'] for q in forms[donor_seed]}
        for target_seed, form in enumerate(forms):
            if target_seed == donor_seed:
                continue
            transferred = {q['id']: donor[q['id']] for q in form if donor[q['id']] in q['options']}
            result = evaluate(target_seed, grade, transferred, specialization, version, form=form)
            scores.append(result['score'])
            if result['passed']:
                passed_pairs.append({'donor_seed': donor_seed, 'target_seed': target_seed, 'score': result['score']})
    constant = sorted(qid for qid, values in answer_values.items() if len(values) == 1)
    return {'specialization': specialization, 'grade': grade, 'version': version,
            'forms': target_count, 'questions_per_form': len(forms[0]),
            'donor_seed_range_inclusive': [0, donor_count - 1],
            'target_seed_range_inclusive': [0, target_count - 1],
            'constant_answer_question_ids_in_sample': constant,
            'constant_answer_questions': len(constant), 'transfer_pairs': len(scores),
            'transferred_score_min': min(scores), 'transferred_score_max': max(scores),
            'transferred_score_mean': round(sum(scores) / len(scores), 2),
            'transferred_passes': len(passed_pairs), 'passing_pairs': passed_pairs}


def legacy_transfer_case(specialization, grade, target_count):
    scores, passed_pairs = [], []
    targets = [questions(seed, grade, specialization, VERSION) for seed in range(target_count)]
    # v3 donor snapshots сохраняются как есть: не превращаются в форму v4.
    for donor_seed in (0, 42, 99):
        snapshot = questions(donor_seed, grade, specialization, 'families-v3')
        donor = {q['id']: q['answer'] for q in snapshot}
        assert evaluate(donor_seed, grade, donor, specialization, 'families-v3', form=snapshot)['score'] == 100
        for seed, form in enumerate(targets):
            transferred = {q['id']: donor[q['id']] for q in form if donor[q['id']] in q['options']}
            result = evaluate(seed, grade, transferred, specialization, form=form)
            scores.append(result['score'])
            if result['passed']:
                passed_pairs.append({'donor_seed': donor_seed, 'target_seed': seed, 'score': result['score']})
    return {'specialization': specialization, 'grade': grade,
            'donor_version': 'families-v3', 'target_version': VERSION,
            'donor_seeds': [0, 42, 99], 'target_seed_range_inclusive': [0, target_count - 1],
            'saved_donor_snapshots_still_score_100': True, 'transfer_pairs': len(scores),
            'transferred_score_max': max(scores), 'transferred_passes': len(passed_pairs),
            'passing_pairs': passed_pairs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--donors', type=int, default=20)
    parser.add_argument('--targets', type=int, default=200)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/assessment-v4-results.json')
    args = parser.parse_args()
    if not 1 <= args.donors < args.targets <= 1000:
        parser.error('Нужно 1 <= donors < targets <= 1000')
    if args.output.resolve() == (ROOT / 'docs/qa-assessment-review-results.json').resolve():
        parser.error('Архивный протокол v3 сохраняется без перезаписи')
    cases, legacy_cases, legacy_transfers = [], [], []
    # Историческая диагностика прежних форм; дизайн появился позже, в сценарных формах (docs/42).
    for specialization in (name for name in CATALOG if name != 'design'):
        for grade in ('junior', 'middle'):
            cases.append(transfer_case(specialization, grade, VERSION, args.donors, args.targets))
            legacy_cases.append(transfer_case(specialization, grade, 'families-v3', args.donors, args.targets))
            legacy_transfers.append(legacy_transfer_case(specialization, grade, args.targets))
    result = {'type': 'assessment_answer_transfer_diagnostic', 'blueprint_version': VERSION,
              'source_sha256': hashlib.sha256((ROOT / 'src/server/assessment.py').read_bytes()).hexdigest(),
              'archived_v3_report': 'docs/qa-assessment-review-results.json',
              'forms_total': args.targets * len(cases),
              'transfer_pairs_total': sum(c['transfer_pairs'] for c in cases), 'cases': cases,
              'same_sample_v3_baseline': legacy_cases, 'v3_to_v4_transfers': legacy_transfers,
              'method': 'Несколько доноров, каждый переносится во все другие формы своей специализации/грейда. Значение переносится по одинаковому question ID только при наличии в options получателя; другие ответы пропущены. Сопоставимая выборка v3; отдельно snapshots v3 seed 0/42/99 в формы v4. HTTP и база не используются.',
              'limitation': 'Конечная внутренняя выборка; отсутствие проходного переноса не доказывает универсальную защиту. Не human pilot, не психометрическая валидация, не проверка переноса алгоритма решения, внешней помощи или API выдачи грейда.'}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'version': VERSION, 'forms': result['forms_total'],
                      'transfer_pairs': result['transfer_pairs_total'],
                      'passing_v4_transfers': sum(c['transferred_passes'] for c in cases),
                      'passing_v3_transfers': sum(c['transferred_passes'] for c in legacy_cases),
                      'passing_v3_to_v4_transfers': sum(c['transferred_passes'] for c in legacy_transfers),
                      'cases': cases}, ensure_ascii=False))


if __name__ == "__main__":
    main()

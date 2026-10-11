"""Синтетическая валидация scenarios-v5: test-retest, разделяющая сила, угадывание.

Что проверяется и чем это НЕ является:
* формы берутся из настоящего генератора (src.server.assessment.questions);
* кандидаты синтетические: латентный уровень theta, профиль навыков, ответы по
  модели 2PL с угадыванием 1/4. Трудности семейств заданий неизвестны (калибровки
  нет), поэтому они берутся из нескольких случайных априорных наборов, а
  результат показывается по всем наборам: это чувствительность к допущению;
* успех ответа не вычисляется из требуемого грейда (theta не привязана к порогу);
* отдельный блок «наивные стратегии» работает только на реальных формах и не
  зависит от модели: проверяет, не выдаёт ли форма ответ позицией/длиной/сходством.
Это не психометрическая калибровка и не пилот с людьми.
"""
import argparse
from collections import Counter
from difflib import SequenceMatcher
import json
import math
from pathlib import Path
import random
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.server.assessment import CATALOG, VERSION, questions  # noqa: E402

THRESHOLD = {'junior': 70, 'middle': 80}
THETAS = (-2.0, -1.0, 0.0, 1.0, 2.0)
GUESS, SLOPE, SKILL_SD = 0.25, 1.2, 0.4


def sigmoid(x):
    return 1 / (1 + math.exp(-x))


def pearson(x, y):
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy) if sx and sy else 0.0


def kappa(a, b):
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n ** 2
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def auc(strong, weak):
    wins = sum((s > w) + 0.5 * (s == w) for s in strong for w in weak)
    return wins / (len(strong) * len(weak))


def priors(spec, grade, families, draw):
    rng = random.Random(f'{spec}/{grade}/{draw}')
    mean = -0.4 if grade == 'junior' else 0.4
    return {family: rng.gauss(mean, 0.5) for family in sorted(families)}


def pool(spec, grade, size, version=VERSION):
    forms = [questions(seed, grade, spec, version) for seed in range(size)]
    families = {q['family'] for form in forms for q in form}
    return forms, families


def take(form, theta, skill_shift, difficulty, rng):
    """Возвращает вектор верности ответов; skill_shift — устойчивый профиль навыков."""
    row = []
    for item in form:
        p = GUESS + (1 - GUESS) * sigmoid(SLOPE * (theta + skill_shift[item['skill']] - difficulty[item['family']]))
        row.append(1 if rng.random() < p else 0)
    return row


def simulate(spec, grade, forms, families, draw, per_level, seed):
    rng = random.Random(f'{seed}/{spec}/{grade}/{draw}')
    difficulty = priors(spec, grade, families, draw)
    skills = sorted({q['skill'] for q in forms[0]})
    rows = []
    for theta in THETAS:
        for _ in range(per_level):
            shift = {s: rng.gauss(0, SKILL_SD) for s in skills}
            first, second = rng.sample(range(len(forms)), 2)
            a = take(forms[first], theta, shift, difficulty, rng)
            b = take(forms[second], theta, shift, difficulty, rng)
            rows.append({'theta': theta, 'forms': (first, second), 'a': a, 'b': b})
    return rows


def category(score, requested_levels):
    for level in requested_levels:
        if score[level] >= THRESHOLD[level]:
            return level
    return 'none'


def summarize(spec, grade, forms, rows):
    n_items = len(forms[0])
    score = lambda v: 100 * sum(v) / len(v)
    sa, sb = [score(r['a']) for r in rows], [score(r['b']) for r in rows]
    pa, pb = [s >= THRESHOLD[grade] for s in sa], [s >= THRESHOLD[grade] for s in sb]
    reliability = pearson(sa, sb)
    sd = statistics.pstdev(sa + sb)
    by_theta = {}
    for theta in THETAS:
        part = [r for r in rows if r['theta'] == theta]
        pas = [score(r['a']) >= THRESHOLD[grade] for r in part]
        both = [(score(r['a']) >= THRESHOLD[grade]) == (score(r['b']) >= THRESHOLD[grade]) for r in part]
        by_theta[str(theta)] = {'mean_score': round(statistics.fmean(score(r['a']) for r in part), 2),
                                'pass_rate': round(statistics.fmean(pas), 3),
                                'decision_agreement': round(statistics.fmean(both), 3)}
    ladder = ('middle', 'junior') if grade == 'middle' else ('junior',)
    cats_a = [category({l: score(r['a']) for l in THRESHOLD}, ladder) for r in rows]
    cats_b = [category({l: score(r['b']) for l in THRESHOLD}, ladder) for r in rows]
    weak = [score(r['a']) for r in rows if r['theta'] == -1.0]
    strong = [score(r['a']) for r in rows if r['theta'] == 1.0]
    pooled = statistics.pstdev(weak + strong) or 1
    # Разделяющая сила заданий: скорректированная item-total и разность верхней/нижней групп.
    items = {}
    order = {}
    for r in rows:
        for idx, item in enumerate(forms[r['forms'][0]]):
            others = sum(r['a']) - r['a'][idx]
            items.setdefault(item['family'], []).append((r['a'][idx], others))
    ranked = sorted(rows, key=lambda r: sum(r['a']))
    k = max(1, int(len(ranked) * 0.27))
    low, high = ranked[:k], ranked[-k:]
    for family, values in sorted(items.items()):
        item_scores = [v for v, _ in values]
        totals = [o for _, o in values]
        order[family] = {'difficulty_p': round(statistics.fmean(item_scores), 3),
                         'item_total_r': round(pearson(item_scores, totals), 3)}
    for family in order:
        up = [r['a'][i] for r in high for i, q in enumerate(forms[r['forms'][0]]) if q['family'] == family]
        lo = [r['a'][i] for r in low for i, q in enumerate(forms[r['forms'][0]]) if q['family'] == family]
        order[family]['upper_lower_D'] = round(statistics.fmean(up) - statistics.fmean(lo), 3)
    return {
        'n_candidates': len(rows), 'items_per_form': n_items,
        'parallel_forms_r': round(reliability, 3),
        'score_sd': round(sd, 2), 'sem_points': round(sd * math.sqrt(max(0, 1 - reliability)), 2),
        'pass_agreement': round(statistics.fmean(x == y for x, y in zip(pa, pb)), 3),
        'pass_kappa': round(kappa(pa, pb), 3),
        'category_agreement': round(statistics.fmean(x == y for x, y in zip(cats_a, cats_b)), 3),
        'category_kappa': round(kappa(cats_a, cats_b), 3),
        'strong_vs_weak_auc': round(auc(strong, weak), 3),
        'strong_vs_weak_cohen_d': round((statistics.fmean(strong) - statistics.fmean(weak)) / pooled, 2),
        'by_theta': by_theta, 'items': order,
        'weak_items_D_below_0_2': sorted(f for f, v in order.items() if v['upper_lower_D'] < 0.2),
    }


STRATEGIES = {
    'first_option': lambda q: q['options'][0],
    'last_option': lambda q: q['options'][-1],
    'longest_option': lambda q: max(q['options'], key=len),
    'shortest_option': lambda q: min(q['options'], key=len),
    'most_similar_to_others': lambda q: max(q['options'], key=lambda o: sum(
        SequenceMatcher(None, o, p).ratio() for p in q['options'] if p != o)),
    'least_similar_to_others': lambda q: min(q['options'], key=lambda o: sum(
        SequenceMatcher(None, o, p).ratio() for p in q['options'] if p != o)),
    'title_numbers_overlap': lambda q: max(q['options'], key=lambda o: len(set(_tokens(o)) & set(_tokens(q['title'])))),
}


def _tokens(text):
    cleaned = ''.join(c if c.isalnum() else ' ' for c in text)
    return cleaned.split()


def naive_strategies(forms):
    total = sum(len(f) for f in forms)
    result = {}
    for name, pick in STRATEGIES.items():
        hits = sum(pick(q) == q['answer'] for form in forms for q in form)
        p = hits / total
        z = (p - 0.25) / math.sqrt(0.25 * 0.75 / total)
        result[name] = {'accuracy': round(p, 4), 'z_vs_chance': round(z, 2)}
    by_family = {}
    for form in forms:
        for q in form:
            row = by_family.setdefault(q['family'], {'n': 0, **{name: 0 for name in STRATEGIES}})
            row['n'] += 1
            for name, pick in STRATEGIES.items():
                row[name] += pick(q) == q['answer']
    worst = {}
    for family, row in sorted(by_family.items()):
        accuracy = {name: row[name] / row['n'] for name in STRATEGIES}
        name = max(accuracy, key=lambda k: abs(accuracy[k] - 0.25))
        worst[family] = {'strategy': name, 'accuracy': round(accuracy[name], 3), 'n': row['n']}
    result['worst_strategy_by_family'] = worst
    position = Counter(q['options'].index(q['answer']) for form in forms for q in form)
    chi = sum((position[i] - total / 4) ** 2 / (total / 4) for i in range(4))
    result['answer_position_counts'] = {str(i): position[i] for i in range(4)}
    result['answer_position_chi2_df3'] = round(chi, 2)
    structural = sum(1 for form in forms for q in form
                     if q['options'].count(q['answer']) != 1 or len(set(q['options'])) != len(q['options']))
    result['malformed_questions'] = structural
    return result


BAND = 6.0


def policy_procedure(rng, theta, shift, rungs, forms_by_grade, difficulty_by_grade, two_stage):
    """Одна процедура подтверждения: ступени Middle -> Junior; у порога при two_stage берётся вторая форма."""
    forms_used = 0
    for grade in rungs:
        forms, difficulty = forms_by_grade[grade], difficulty_by_grade[grade]
        first = 100 * sum(take(rng.choice(forms), theta, shift, difficulty, rng)) / 12
        forms_used += 1
        score = first
        if two_stage and abs(first - THRESHOLD[grade]) <= BAND:
            second = 100 * sum(take(rng.choice(forms), theta, shift, difficulty, rng)) / 12
            forms_used += 1
            score = (first + second) / 2
        if score >= THRESHOLD[grade]:
            return grade, forms_used
    return 'none', forms_used


def policy_comparison(spec, pool_size, per_level, draws, seed):
    """Согласие итоговой категории при повторе процедуры: одна форма против подтверждающей второй у порога."""
    out = {}
    for label, rungs in (('middle_ladder', ('middle', 'junior')), ('junior_only', ('junior',))):
        rows = {'single': [], 'two_stage': []}
        for draw in range(draws):
            forms_by_grade, difficulty_by_grade = {}, {}
            for grade in rungs:
                forms, families = pool(spec, grade, pool_size, 'scenarios-v6')
                forms_by_grade[grade], difficulty_by_grade[grade] = forms, priors(spec, grade, families, draw)
            skills = sorted({q['skill'] for q in forms_by_grade[rungs[0]][0]})
            for policy in ('single', 'two_stage'):
                rng = random.Random(f'{seed}/policy/{spec}/{label}/{draw}')   # одинаковые кандидаты для обеих политик
                agree, first_runs, second_runs, used = [], [], [], 0
                for theta in THETAS:
                    for _ in range(per_level):
                        shift = {s: rng.gauss(0, SKILL_SD) for s in skills}
                        a, ua = policy_procedure(rng, theta, shift, rungs, forms_by_grade, difficulty_by_grade, policy == 'two_stage')
                        b, ub = policy_procedure(rng, theta, shift, rungs, forms_by_grade, difficulty_by_grade, policy == 'two_stage')
                        first_runs.append(a); second_runs.append(b); used += ua + ub
                rows[policy].append({'agreement': statistics.fmean(x == y for x, y in zip(first_runs, second_runs)),
                                     'kappa': kappa(first_runs, second_runs), 'forms_per_procedure': used / (2 * len(first_runs))})
        out[label] = {policy: {k: {'min': round(min(r[k] for r in data), 3), 'max': round(max(r[k] for r in data), 3)}
                               for k in ('agreement', 'kappa', 'forms_per_procedure')} for policy, data in rows.items()}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pool', type=int, default=400, help='число различных форм на пару специализация/грейд')
    parser.add_argument('--per-level', type=int, default=300, help='кандидатов на уровень theta')
    parser.add_argument('--draws', type=int, default=5, help='число априорных наборов трудностей')
    parser.add_argument('--seed', type=int, default=20261008)
    parser.add_argument('--version', default=VERSION, help='scenarios-v5 или scenarios-v6')
    parser.add_argument('--output', type=Path, default=None)
    parser.add_argument('--policy', action='store_true', help='сравнить политику подтверждающей формы (только v6)')
    args = parser.parse_args()
    args.output = args.output or ROOT / f'docs/retest-validation-{args.version}.json'
    out = {'blueprint': args.version, 'method': {
        'model': '2PL с угадыванием 0.25; slope 1.2; профиль навыков N(0,0.4) постоянен между формами',
        'thetas': THETAS, 'difficulty_prior': 'N(-0.4|+0.4, 0.5) по семействам; наборов: %d' % args.draws,
        'pool': args.pool, 'per_level': args.per_level, 'seed': args.seed,
        'limits': 'Синтетические кандидаты и допущенные трудности; не калибровка Junior/Middle и не пилот с людьми.'},
        'combos': {}}
    for spec in CATALOG:
        for grade in THRESHOLD:
            forms, families = pool(spec, grade, args.pool, args.version)
            draws = [summarize(spec, grade, forms, simulate(spec, grade, forms, families, d, args.per_level, args.seed))
                     for d in range(args.draws)]
            keys = ('parallel_forms_r', 'sem_points', 'pass_agreement', 'pass_kappa', 'category_agreement',
                    'category_kappa', 'strong_vs_weak_auc', 'strong_vs_weak_cohen_d')
            span = {k: {'min': min(d[k] for d in draws), 'median': statistics.median(d[k] for d in draws),
                        'max': max(d[k] for d in draws)} for k in keys}
            weak = Counter(f for d in draws for f in d['weak_items_D_below_0_2'])
            out['combos'][f'{spec}/{grade}'] = {
                'across_priors': span,
                'items_with_low_D_in_n_priors': dict(sorted(weak.items())),
                'example_draw_0': {k: draws[0][k] for k in ('by_theta', 'items')},
                'naive_strategies_real_forms': naive_strategies(forms)}
    if args.policy:
        out['confirmation_policy'] = {spec: policy_comparison(spec, args.pool, args.per_level, args.draws, args.seed) for spec in CATALOG}
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'Записано: {args.output}')


if __name__ == '__main__':
    main()

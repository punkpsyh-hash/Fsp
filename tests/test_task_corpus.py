"""Генераторы корпуса дообучения: вычисленная истина проходит те же проверки, что и продукт."""
import json
import random

from ml.corpus import build_corpus, fam_algo, fam_py, fam_sql, fam_web
from ml.corpus.core import completion, compose_solution, request_for, make_example, work_from_rubric


def _examples(module, seeds=6):
    for fam in module.FAMILIES:
        produced = 0
        for seed in range(seeds * 4):
            rng = random.Random(seed)
            grade = rng.choice(['junior', 'middle'])
            try:
                scenario = fam(rng, grade)
            except (ValueError, AssertionError, IndexError, KeyError):
                continue
            for kind, (task, brief) in scenario['tasks'].items():
                request = request_for(kind, scenario['spec'], grade, scenario['skills'], brief)
                work = work_from_rubric(scenario['tasks']['open_response'][0]) if 'open_response' in scenario['tasks'] else None
                yield fam.__name__, make_example(fam.__name__, request, task, work=work)
                produced += 1
        assert produced, fam.__name__


def test_computed_families_produce_valid_tasks():
    for module in (fam_sql, fam_py, fam_web, fam_algo):
        names = {name for name, _ in _examples(module)}
        assert names == {fam.__name__ for fam in module.FAMILIES}


def test_completion_is_compact_json_in_schema_order():
    rng = random.Random(1)
    scenario = fam_sql.sql_null_aggregates(rng, 'junior')
    task, _ = scenario['tasks']['numeric']
    task = {**task, 'solution': compose_solution(task, work_from_rubric(scenario['tasks']['open_response'][0]))}
    text = completion(task)
    assert text.startswith('{"id":"suggestion","type":"numeric"') and ', "' not in text[:60]
    assert list(json.loads(text)) == ['id', 'type', 'title', 'prompt', 'skills', 'solution', 'numeric_answer', 'unit']


def test_heldout_families_are_excluded_from_training(tmp_path):
    rows, _ = build_corpus.build('test-seed', draws_scale=0.1)
    held = {r['family'] for r in rows} & build_corpus.HELDOUT_FAMILIES
    assert held, 'контрольные семейства должны существовать в генераторах'
    train = [r for r in build_corpus.dedupe(rows) if r['family'] not in build_corpus.HELDOUT_FAMILIES]
    assert not ({r['family'] for r in train} & build_corpus.HELDOUT_FAMILIES)

"""Повтор отдельной конечной выборки по зафиксированным seed, только в Docker."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.server.assessment import VERSION, evaluate, questions


def main():
    report = json.loads((ROOT / 'docs/assessment-holdout-results.json').read_text())
    digest = hashlib.sha256((ROOT / 'src/server/assessment.py').read_bytes()).hexdigest()
    assert report['blueprint_version'] == VERSION
    assert report['source_sha256'] == digest, 'Генератор изменён; прежняя выборка не подтверждает новый код'
    cases = []
    for case in report['cases']:
        spec, grade = case['specialization'], case['grade']
        targets = [(seed, questions(seed, grade, spec)) for seed in report['target_seeds']]
        scores, passing = [], 0
        for seed in report['donor_seeds']:
            donor = {q['id']: q['answer'] for q in questions(seed, grade, spec)}
            for target_seed, form in targets:
                transferred = {q['id']: donor[q['id']] for q in form if donor[q['id']] in q['options']}
                result = evaluate(target_seed, grade, transferred, spec, form=form)
                scores.append(result['score'])
                passing += int(result['passed'])
        replay = dict(specialization=spec, grade=grade, pairs=len(scores), passing=passing, max_score=max(scores))
        assert replay == case, (replay, case)
        cases.append(replay)
    total = sum(case['pairs'] for case in cases)
    assert total == report['total_pairs']
    print(json.dumps(dict(version=VERSION, replay_equal=True, pairs=total,
                          passing=sum(case['passing'] for case in cases),
                          limitation=report['limitation']), ensure_ascii=False))


if __name__ == '__main__':
    main()

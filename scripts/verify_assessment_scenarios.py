"""Конечная техническая диагностика v5 и совместимости, не human pilot."""
import argparse
from collections import Counter
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.server.assessment import CATALOG, VERSION, evaluate, questions, public_question_form
from tests.test_assessment_scenarios import donor_probe, encoded, oracle, shown_python_result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/assessment-v5-results.json')
    args=parser.parse_args()
    module_spec=importlib.util.spec_from_file_location('historical_v4',args.baseline)
    baseline=importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(baseline)
    assert VERSION=='scenarios-v5' and baseline.VERSION=='families-v4'
    historical_count=0
    for version in ('demo-backend-v1','families-v2','families-v3','families-v4'):
        for spec in CATALOG:
            for grade in ('junior','middle'):
                for seed in (-1,*range(100),2147483647):
                    old=baseline.questions(seed,grade,spec,version)
                    current=questions(seed,grade,spec,version)
                    assert json.dumps(old,ensure_ascii=False).encode()==json.dumps(current,ensure_ascii=False).encode()
                    assert baseline.round_questions(seed,grade,spec,version)==__import__('src.server.assessment',fromlist=['round_questions']).round_questions(seed,grade,spec,version)
                    assert baseline.public_questions(seed,grade,spec,version)==public_question_form(current)
                    answers={q['id']:q['answer'] for q in old}
                    assert baseline.evaluate(seed,grade,answers,spec,version)==evaluate(seed,grade,answers,spec,version)
                    historical_count+=1
    matrices=[]
    for spec in CATALOG:
        for grade in ('junior','middle'):
            signatures=set()
            for seed in range(100):
                private=questions(seed,grade,spec)
                assert Counter(q['skill'] for q in private)==Counter({s:4 for s in CATALOG[spec]['skills']})
                public=public_question_form(private)
                assert len(public)==12 and len({q['id'] for q in public})==12
                answers={q['id']:encoded(oracle(q)) for q in public}
                assert all(answers[q['id']]==q['answer'] for q in private)
                for q in public:
                    if q['family'].startswith('py-'):
                        assert encoded(shown_python_result(q))==answers[q['id']]
                assert evaluate(seed,grade,answers,spec,form=private)['score']==100
                signatures.add(json.dumps(public,sort_keys=True,ensure_ascii=False))
            matrices.append({'specialization':spec,'grade':grade,'forms':100,'distinct_forms':len(signatures),
                             'questions':12,'per_skill':4,'independent_oracles':'passed'})
    report={'blueprint_version':VERSION,'historical':{'forms':historical_count,'byte_equality':True,
             'round_public_evaluate_equal':True,'baseline_commit':'0311fe3937c8096a065c001bb69f642cc36fbe61',
             'baseline_source_sha256':sha256(args.baseline.read_bytes()).hexdigest()},
            'forms_total':600,'matrices':matrices,'transfer':donor_probe(),
            'source_sha256':{name:sha256((ROOT/name).read_bytes()).hexdigest() for name in
                ('src/server/assessment.py','src/server/assessment_scenarios.py','src/server/assessment_feedback.py',
                 'tests/test_assessment_scenarios.py','web/scripts/scenario-oracle.mjs')},
            'limitations':['Конечные синтетические выборки, без независимого профессионального пилота.',
                           'Совпадение вычислений не подтверждает равную сложность или пригодность порогов.',
                           'Перенос позиций вариантов имеет редкие проходы; универсальная защита от внешней помощи не заявляется.']}
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'version':VERSION,'historical_forms':historical_count,'forms':600,
                      'transfer':report['transfer']},ensure_ascii=False))


if __name__=='__main__':main()

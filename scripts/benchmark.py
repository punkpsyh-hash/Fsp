"""Внутренний benchmark с отдельно записанной разметкой, не human pilot."""
import json
from math import log2
from pathlib import Path
from collections import Counter
from src.domain import Candidate, Need, rank
from src.server.assessment import CATALOG, VERSION, questions, evaluate

ROOT=Path(__file__).resolve().parents[1]


def ranking_benchmark():
    dataset=json.loads((ROOT/'requirements/examples/ranking-benchmark.json').read_text())
    profiles=[]
    for spec in dataset['specializations']:
        for row in dataset['profile_templates']:
            profiles.append(Candidate(spec['prefix']+row['suffix'],spec['id'],row['grade'],
                            frozenset(spec['skills'][i] for i in row['skills']),row['test_score'],
                            row['fsp_signal'],row['freshness'],row['published'],
                            frozenset(row['formats']),row['salary_min']))
    reports=[]
    for row in dataset['needs']:
        need=Need(row['specialization'],row['grade'],frozenset(row['must']),frozenset(row['desired']),row['salary_to'],row['format'])
        result=rank(profiles,need)
        top=result[:3]; labels=row['labels']; denominator=min(3,len(labels))
        precision=sum(labels.get(item['id'],0)>0 for item in top)/denominator
        dcg=lambda values: sum((2**value-1)/log2(i+2) for i,value in enumerate(values))
        ideal=dcg(sorted(labels.values(),reverse=True)[:3])
        ndcg=dcg([labels.get(item['id'],0) for item in top])/ideal if ideal else 0
        # Отдельная аннотация hard-filter нарушений: положительные ID заданы заранее.
        violations=[item['id'] for item in result if item['id'] not in labels]
        reports.append({'need':row['id'],'ranking':[item['id'] for item in result],
                        'precision_at_3':round(precision,6),'ndcg_at_3':round(ndcg,6),
                        'filter_violations':violations,'labels':labels})
    return {'profiles':len(profiles),'needs':len(reports),'algorithm_version':'weighted-v1',
            'method':dataset['method'],'precision_at_3':round(sum(r['precision_at_3'] for r in reports)/len(reports),6),
            'ndcg_at_3':round(sum(r['ndcg_at_3'] for r in reports)/len(reports),6),
            'filter_violations':sum(len(r['filter_violations']) for r in reports),'cases':reports}


def assessment_benchmark():
    forms=[]
    for spec in CATALOG:
        for grade in ('junior','middle'):
            signatures=set(); family_distributions=Counter()
            for seed in range(100):
                form=questions(seed,grade,spec)
                signature=tuple(sorted((row['id'],row['title'],tuple(row['options'])) for row in form))
                signatures.add(signature)
                family_distributions.update(row['family'] for row in form)
                answer={row['id']:row['answer'] for row in form}
                correct=evaluate(seed,grade,answer,spec)
                assert correct['passed'] and correct['score']==100
                wrong={row['id']:next(value for value in row['options'] if value!=row['answer']) for row in form}
                assert not evaluate(seed,grade,wrong,spec)['passed']
                counts=Counter(row['skill'] for row in form)
                assert set(counts.values())=={4}
            forms.append({'specialization':spec,'grade':grade,'forms':100,'distinct_forms':len(signatures),
                          'questions_per_form':12,'questions_per_skill':4,'family_counts':dict(family_distributions),
                          'correct_and_wrong_extremes_pass':True})
    return {'version':VERSION,'forms':sum(row['forms'] for row in forms),'matrix_checks':forms,
            'limitation':'Техническая воспроизводимость и равная матрица. Экспертная калибровка сложности, различимость кандидатов и устойчивость к внешней помощи не доказаны.'}


def main():
    result={'type':'internal_synthetic_benchmark','ranking':ranking_benchmark(),
            'assessment':assessment_benchmark(),'human_pilot':False,
            'limitation':'Малый внутренний synthetic benchmark, разметка команды. Не независимая экспертная оценка, профессиональная сертификация или качество реального найма.'}
    (ROOT/'docs/benchmark-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result['ranking'].items() if k!='cases'},ensure_ascii=False,indent=2))
    if result['ranking']['filter_violations']: raise SystemExit(1)


if __name__=='__main__': main()

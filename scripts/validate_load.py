"""Контролируемый локальный замер 30 параллельных клиентов на синтетической БД.
Это один сценарий и одна учётная запись, не доказательство поведения разных пользователей.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import statistics
import time
import httpx

ROOT=Path(__file__).resolve().parents[1]
with httpx.Client(base_url='http://127.0.0.1:8470',timeout=20) as client:
    auth=client.post('/api/v1/auth/demo-login',json={'user_id':'demo-employer-x'});auth.raise_for_status()
    csrf=auth.json()['csrf']
    def operation(index):
        start=time.perf_counter()
        if index%2:
            response=client.get('/api/v1/company/candidates/demo-candidate-a')
        else:
            response=client.post('/api/v1/company/searches',json={'specialization':'backend','grade':'junior','salary_to':200000,'must_skills':['python'],'desired_skills':['sql']},headers={'X-CSRF-Token':csrf})
        return {'duration_ms':round((time.perf_counter()-start)*1000,2),'status':response.status_code,'operation':'profile' if index%2 else 'search'}
    start=time.perf_counter()
    with ThreadPoolExecutor(max_workers=30) as workers:results=list(workers.map(operation,range(90)))
    elapsed=time.perf_counter()-start
    report={'type':'local_synthetic_load','concurrency':30,'requests':90,'elapsed_seconds':round(elapsed,2),'errors':sum(r['status']>=400 for r in results),'operations':{},'limitation':'Один локальный сценарий, одна синтетическая учётная запись. Не human pilot, не испытание реальных ПДн или распределённой нагрузки.'}
    for kind in ['search','profile']:
        durations=sorted(r['duration_ms'] for r in results if r['operation']==kind)
        report['operations'][kind]={'requests':len(durations),'p50_ms':round(statistics.median(durations),2),'p95_ms':durations[int(.95*(len(durations)-1))],'max_ms':max(durations)}
    (ROOT/'docs'/'load-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if report['errors']:raise SystemExit(1)

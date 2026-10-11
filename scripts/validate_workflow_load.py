"""30 независимых синтетических аккаунтов, полный обратный подбор и отзыв.

Создаёт только собственные synthetic записи. Не удаляет данные и не печатает
пароли, контакты или payload. Oracle формы читает доверенный tools-процесс:
это техническая нагрузка с эталонными ответами, а не испытание знаний людей.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier, Lock
from uuid import uuid4
import json
import secrets
import statistics
import time
import httpx
from src.server.db import database, database_url
from src.server.models import User, Profile, Contact, Attempt, now
from src.server.security import password_hash

ROOT=Path(__file__).resolve().parents[1]
PAIRS=15


def main():
    run=uuid4().hex[:12]
    engine,factory=database(database_url())
    accounts=[]
    with factory() as db:
        for index in range(PAIRS):
            for role in ('candidate','employer'):
                key=f'load-{run}-{index}-{role}'
                password=secrets.token_urlsafe(24)
                user=User(id=key,email=key+'@example.invalid',role=role,
                          label=f'Нагрузочный пример {index} · {role}',verified=True,
                          demo_seed=False,password_hash=password_hash(password))
                db.add(user); db.flush()
                if role=='candidate':
                    db.add(Profile(user_id=key,specialization='backend',claimed_grade='junior',
                                   resume={'full_name':'Синтетический участник','years_experience':1,
                                           'roles':['developer'],'soft_skills':['teamwork'],'education':'','about':''}))
                    db.add(Contact(user_id=key,value=key+'@example.invalid'))
                accounts.append({'id':key,'role':role,'index':index,'password':password})
        db.commit()
    barrier=Barrier(30,timeout=120); records=[]; lock=Lock(); failures=[]
    invitations={}
    def worker(account):
        index=account['index']; role=account['role']
        partner=f'load-{run}-{index}-'+('candidate' if role=='employer' else 'employer')
        with httpx.Client(base_url='http://127.0.0.1:8470',timeout=45) as client:
            csrf=''
            def call(operation,method,path,body=None,headers=None):
                start=time.perf_counter()
                response=client.request(method,path,json=body,
                    headers={**({'X-CSRF-Token':csrf} if method!='GET' else {}),**(headers or {})})
                with lock:
                    records.append({'operation':operation,'duration_ms':round((time.perf_counter()-start)*1000,2),
                                    'status':response.status_code})
                response.raise_for_status()
                return response.json() if response.content and response.headers.get('content-type','').startswith('application/json') else None
            try:
                auth=call('login','POST','/api/v1/auth/password-login',
                          {'email':account['id']+'@example.invalid','password':account['password']})
                csrf=auth['csrf']
                if role=='candidate':
                    call('profile','GET','/api/v1/candidate/profile')
                    attempt=call('assessment_start','POST','/api/v1/assessments/attempts',{'grade':'junior'})
                    with factory() as db:
                        form=db.get(Attempt,attempt['id']).question_form
                        answers={q['id']:q['answer'] for q in form}
                    call('assessment_draft','PUT','/api/v1/assessments/attempts/'+attempt['id']+'/draft',
                         {'answers':answers,'expected_revision':attempt['revision']})
                    assert call('assessment_submit','POST','/api/v1/assessments/attempts/'+attempt['id']+'/submit',{'answers':answers})['passed']
                    call('consent','POST','/api/v1/candidate/consents',{'published':True})
                else:
                    call('company','GET','/api/v1/company/profile')
                barrier.wait()
                if role=='employer':
                    result=call('search','POST','/api/v1/company/searches',{'salary_to':200000})
                    assert partner in result['candidate_ids']
                    profile=call('profile','GET','/api/v1/company/candidates/'+partner)
                    assert 'contact' not in profile
                    offer=call('invitation','POST','/api/v1/company/invitations',
                         {'candidate_id':partner,'description':'Нагрузочный синтетический пример: Python и SQL, удалённая команда.',
                          'salary_from':120000,'salary_to':180000,'salary_basis':'gross'},
                         {'Idempotency-Key':f'load-{run}-{index}'})
                    with lock: invitations[index]=offer['id']
                else:
                    call('profile','GET','/api/v1/candidate/profile')
                barrier.wait()
                if role=='candidate':
                    call('invitations_list','GET','/api/v1/candidate/invitations')
                    call('accept','POST','/api/v1/candidate/invitations/'+invitations[index]+'/decision',{'decision':'accepted'})
                else:
                    call('invitations_list','GET','/api/v1/company/invitations')
                barrier.wait()
                if role=='employer':
                    assert call('contact','GET','/api/v1/company/candidates/'+partner)['contact'].endswith('@example.invalid')
                    call('pdf','GET','/api/v1/company/candidates/'+partner+'/profile.pdf')
                    assert call('restore','GET','/api/v1/company/searches/'+result['id'])['historical_explanation']
                barrier.wait()
                if role=='candidate':
                    call('revoke','DELETE','/api/v1/candidate/contacts/'+partner)
                barrier.wait()
                if role=='employer':
                    assert 'contact' not in call('contact_after_revoke','GET','/api/v1/company/candidates/'+partner)
            except Exception as error:
                barrier.abort()
                with lock: failures.append({'role':role,'index':index,'error_type':type(error).__name__})
    start=time.perf_counter()
    with ThreadPoolExecutor(max_workers=30) as workers: list(workers.map(worker,accounts))
    operations={}
    for kind in sorted({r['operation'] for r in records}):
        durations=sorted(r['duration_ms'] for r in records if r['operation']==kind)
        operations[kind]={'requests':len(durations),'p50_ms':round(statistics.median(durations),2),
                          'p95_ms':durations[int(.95*(len(durations)-1))],'max_ms':max(durations)}
    report={'type':'multi_account_workflow_load','at':datetime.now(timezone.utc).isoformat(),
            'accounts':30,'concurrency':30,'pairs':15,'requests':len(records),
            'elapsed_seconds':round(time.perf_counter()-start,2),'errors':sum(r['status']>=400 for r in records),
            'failed_workflows':failures,'operations':operations,
            'limitation':'30 новых синтетических аккаунтов; email подтверждён seed, решения эталонные. Работа от оценки до предложения/контакта/отзыва. Не human pilot, не реальные ПДн; runner нагрузка измеряется отдельно.'}
    (ROOT/'docs/workflow-load-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    engine.dispose()
    if report['errors'] or failures: raise SystemExit(1)


if __name__=='__main__': main()

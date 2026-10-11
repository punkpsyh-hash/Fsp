"""Сквозные проверки нового объёма: роли, реальные состояния и отрицательные сценарии."""
from datetime import timedelta
from io import BytesIO
import secrets
import pytest
from pypdf import PdfReader
from sqlalchemy import select
from tests.test_api import client, login, register
from src.server.assessment import CATALOG, VERSION, evaluate, questions
from src.server.models import Attempt, Mail, Profile, TaskResponse, User, now


def vacancy(**changes):
    data=dict(title='Синтетическая вакансия для проверки',description='Разработка тестового API без настоящих персональных данных.',specialization='backend',grade='junior',skills=['python','sql'],format='remote',salary_from=120000,salary_to=180000,salary_basis='net',status='published')
    data.update(changes);return data


def update_profile(client,spec='backend',**changes):
    body=dict(specialization=spec,claimed_grade='junior',salary_min=100000,formats=['remote'],contact='test@example.invalid')
    body.update(changes);return client.put('/api/v1/candidate/profile',json=body)


def complete_attempt(client,spec='backend',**changes):
    r=client.post('/api/v1/assessments/attempts',json=dict(specialization=spec,grade='junior',**changes));assert r.status_code==201,r.text
    attempt=r.json()
    with client.app.state.factory() as db:
        a=db.get(Attempt,attempt['id']);answers={q['id']:q['answer'] for q in a.question_form}
    r=client.post(f"/api/v1/assessments/attempts/{attempt['id']}/submit",json={'answers':answers});assert r.status_code==200,r.text
    return r.json()


def test_company_profile_need_categories_and_private_search_restore(client):
    login(client,'employer-x')
    body=dict(name='Тестовая команда',description='Синтетическая команда для проверки профиля компании.',industry='Разработка',contact='company@example.invalid')
    assert client.put('/api/v1/company/profile',json=body).status_code==200
    assert client.get('/api/v1/company/profile').json()['name']==body['name']
    need=client.post('/api/v1/company/needs',json=dict(title='Поиск Frontend',description='Интерфейсы и доступные формы на JavaScript.',specialization='frontend',grade='junior',must_skills=['javascript'],desired_skills=['html'],salary_to=180000,format='remote'))
    assert need.status_code==201
    query=need.json()['query'];search=client.post('/api/v1/company/searches',json=query).json()
    assert search['rows'][0]['specialization']=='frontend'
    key=search['id'];assert client.get('/api/v1/company/searches/'+key).json()['rows']
    assert sum(c['count'] for c in client.get('/api/v1/company/categories').json())==5
    login(client,'employer-y')
    assert all(n['id']!=need.json()['id'] for n in client.get('/api/v1/company/needs').json())
    assert client.get('/api/v1/company/searches/'+key).status_code==404
    login(client,'candidate-c');assert client.post('/api/v1/candidate/consents',json={'published':False}).status_code==200
    login(client,'employer-x');assert client.get('/api/v1/company/searches/'+key).json()['rows']==[]


def test_vacancy_ownership_versions_and_salary(client):
    login(client,'employer-x');r=client.post('/api/v1/company/vacancies',json=vacancy());assert r.status_code==201
    v=r.json();key=v['id']
    assert client.put('/api/v1/company/vacancies/'+key,json=vacancy(expected_version=99)).status_code==409
    assert client.put('/api/v1/company/vacancies/'+key,json=vacancy(expected_version=1,title='Обновлённая тестовая вакансия')).json()['version']==2
    for value in (-1,True,12.3,'120000'):
        assert client.post('/api/v1/company/vacancies',json=vacancy(salary_from=value)).status_code==422
    login(client,'employer-y');assert client.put('/api/v1/company/vacancies/'+key,json=vacancy(expected_version=2)).status_code==404
    login(client,'candidate-a');assert any(v['id']==key for v in client.get('/api/v1/candidate/vacancies').json())


def test_application_grant_snapshot_roles_withdraw_and_revoke(client):
    login(client,'employer-x');v=client.post('/api/v1/company/vacancies',json=vacancy()).json();key=v['id']
    login(client,'candidate-a');r=client.post('/api/v1/candidate/vacancies/'+key+'/apply');assert r.status_code==201
    a=r.json();assert client.post('/api/v1/candidate/vacancies/'+key+'/apply').json()['id']==a['id']
    login(client,'candidate-b');assert client.post('/api/v1/candidate/applications/'+a['id']+'/withdraw').status_code==404
    assert client.get('/api/v1/candidate/applications').json()==[]
    login(client,'employer-y');assert client.post('/api/v1/company/applications/'+a['id']+'/decision',json={'status':'accepted'}).status_code==404
    assert 'contact' not in client.get('/api/v1/company/candidates/demo-candidate-a').json()
    login(client,'employer-x');assert client.get('/api/v1/company/applications').json()[0]['contact'].endswith('@example.invalid')
    assert 'contact' in client.get('/api/v1/company/candidates/demo-candidate-a').json()
    client.put('/api/v1/company/vacancies/'+key,json=vacancy(expected_version=1,salary_from=160000))
    assert client.get('/api/v1/company/applications').json()[0]['snapshot']['salary_from']==120000
    login(client,'candidate-a');client.delete('/api/v1/candidate/contacts/demo-employer-x')
    login(client,'employer-x');assert 'contact' not in client.get('/api/v1/company/candidates/demo-candidate-a').json()
    # Повторная отправка старого отклика не восстанавливает разрешение.
    login(client,'candidate-a');client.post('/api/v1/candidate/vacancies/'+key+'/apply')
    client.post('/api/v1/candidate/applications/'+a['id']+'/withdraw')
    login(client,'employer-x');assert client.post('/api/v1/company/applications/'+a['id']+'/decision',json={'status':'accepted'}).status_code==409


def test_task_periodic_delivery_review_owned_and_not_grade_mutation(client):
    login(client,'candidate-a');tasks=client.get('/api/v1/candidate/tasks').json()['available'];assert tasks
    task=tasks[0]
    r=client.post('/api/v1/candidate/tasks/'+task['id']+'/submit',json={'answer':'Проверю роль отправителя, другой компании и отзыв контакта.'});assert r.status_code==201
    key=r.json()['id'];assert client.get('/api/v1/candidate/tasks').json()['available']==[]
    assert client.post('/api/v1/candidate/tasks/demo-task-frontend/submit',json={'answer':'Синтетический ответ достаточно длинный.'}).status_code==404
    login(client,'employer-y');assert client.get('/api/v1/company/task-responses').json()==[]
    assert client.post('/api/v1/company/task-responses/'+key+'/review',json={'score':90,'feedback':'Проверки прав доступа перечислены достаточно полно.'}).status_code==404
    login(client,'employer-x');review={'score':90,'feedback':'Проверки прав доступа перечислены достаточно полно.'}
    assert client.post('/api/v1/company/task-responses/'+key+'/review',json=review).status_code==200
    assert client.post('/api/v1/company/task-responses/'+key+'/review',json={**review,'score':10}).status_code==409
    login(client,'candidate-a');p=client.get('/api/v1/candidate/profile').json()
    assert p['activity_at'] and p['confirmed_grade']=='junior' and p['test_score']==90
    with client.app.state.factory() as db:
        db.get(TaskResponse,key).submitted_at=now()-timedelta(days=8);db.commit()
    assert client.get('/api/v1/candidate/tasks').json()['next_at']


@pytest.mark.parametrize('spec',list(CATALOG))
def test_assessment_context_category_history_and_ownership(client,spec):
    register(client);assert update_profile(client,spec).status_code==200
    result=complete_attempt(client,spec,vacancy_id='demo-vacancy-'+spec)
    assert result['passed'] and result['version']==VERSION and len(result['breakdown'])==3
    p=client.get('/api/v1/candidate/profile').json();assert p['specialization']==spec and p['confirmed_grade']=='junior'
    history=client.get('/api/v1/candidate/assessment-history').json()
    assert history['attempts'][0]['context']['source']=='vacancy' and len(history['events'])==1
    login(client,'candidate-b');assert client.get('/api/v1/candidate/assessment-history').json()['attempts']==[]


def test_specialization_switch_cannot_bypass_grade_cooldown(client):
    login(client,'candidate-a');update_profile(client,'frontend')
    assert client.get('/api/v1/candidate/profile').json()['confirmed_grade'] is None
    update_profile(client,'backend')
    assert client.get('/api/v1/candidate/profile').json()['confirmed_grade']=='junior'
    assert client.post('/api/v1/assessments/attempts',json={'specialization':'backend','grade':'middle'}).status_code==409


def test_password_registration_confirmation_login_and_rate_limit(client):
    password=secrets.token_urlsafe(18)
    body={'email':'password@example.invalid','role':'candidate','label':'Тестовый профиль','consent':True,'password':password}
    assert client.post('/api/v1/auth/register',json=body).status_code==201
    assert client.post('/api/v1/auth/password-login',json={'email':body['email'],'password':password}).status_code==403
    token=client.get('/api/v1/auth/mock-mail').json()[0]['token'];client.post('/api/v1/auth/verify',json={'token':token})
    r=client.post('/api/v1/auth/password-login',json={'email':body['email'],'password':password});assert r.status_code==200
    with client.app.state.factory() as db:
        user=db.scalar(select(User).where(User.email==body['email']))
        assert password not in user.password_hash and user.password_hash.startswith('pbkdf2_sha256$600000$')
    for _ in range(30):r=client.post('/api/v1/auth/password-login',json={'email':body['email'],'password':secrets.token_urlsafe(12)})
    assert r.status_code==429 and r.headers['retry-after']=='60'


def test_fsp_filter_privacy_pdf_preview_and_view_state(client):
    from tests.test_fsp_id import link
    login(client,'candidate-a');link(client)
    p=client.get('/api/v1/candidate/profile').json();assert p['fsp_member_id']=='FSP-1001' and p['fsp_evidence'][0]['demo']
    pdf=client.get('/api/v1/candidate/profile.pdf').content
    preview=client.post('/api/v1/candidate/resume-preview',content=pdf,headers={'Content-Type':'application/pdf'})
    assert preview.status_code==200 and preview.json()['contact'].endswith('@example.invalid')
    assert client.post('/api/v1/candidate/resume-preview',content=b'not-pdf',headers={'Content-Type':'application/pdf'}).status_code==422
    assert client.post('/api/v1/candidate/resume-preview',content=b'x'*(2*1024*1024+1),headers={'Content-Type':'application/pdf'}).status_code==413
    assert client.post('/api/v1/candidate/resume-preview',content=pdf).status_code==415
    login(client,'employer-x');r=client.post('/api/v1/company/searches',json={'fsp_only':True})
    assert r.json()['candidate_ids']==['demo-candidate-a'] and 'FSP-1001' not in r.text
    offer=client.post('/api/v1/company/invitations',headers={'Idempotency-Key':'view-state-123'},json={'candidate_id':'demo-candidate-a','description':'Тестовое предложение достаточно длинное.','salary_from':100000,'salary_to':150000,'salary_basis':'gross'}).json()
    login(client,'candidate-a');assert client.post('/api/v1/candidate/invitations/'+offer['id']+'/view').json()['status']=='viewed'


def test_v4_form_variation_reference_wrong_answers_and_fixed_skill_coverage():
    for spec in ('backend','frontend','qa'):
        for grade in ('junior','middle'):
            forms=set()
            for seed in range(100):
                form=questions(seed,grade,spec,'families-v4');assert form==questions(seed,grade,spec,'families-v4')
                forms.add(str(form));assert len(form)==12
                assert {q['skill'] for q in form}==set(CATALOG[spec]['skills'])
                assert all(len(q['options'])==len(set(q['options']))==4 for q in form)
                assert all(int(q['answer']) >= 0 for q in form)
                answers={q['id']:q['answer'] for q in form};assert evaluate(seed,grade,answers,spec,'families-v4')['score']==100
                wrong={q['id']:next(a for a in q['options'] if a!=q['answer']) for q in form};assert evaluate(seed,grade,wrong,spec,'families-v4')['score']==0
            assert len(forms)==100


def test_reference_answers_are_independently_calculated():
    expected={
        'backend':{'python-range':'8','python-state':'18','sql-count':'14','sql-join':'4','http-retry':'1','http-access':'14'},
        'frontend':{'js-map':'36','js-filter':'8','html-focus':'14','html-label':'14','http-retry':'1','http-access':'14'},
        'qa':{'test-boundaries':'17','test-cases':'32','sql-count':'14','sql-join':'4','http-retry':'1','http-access':'14'},
    }
    # seed 42: n=16, k=2. Эталонная таблица посчитана независимо от grader.
    for spec,answers in expected.items():
        assert {q['id']:q['answer'] for q in questions(42,'junior',spec,'families-v2')}==answers
    middle=expected['backend']|{'python-state':'3','sql-join':'18'}
    assert {q['id']:q['answer'] for q in questions(42,'middle','backend','families-v2')}==middle


def test_smtp_adapter_delivers_over_verified_tls_locally(tmp_path,monkeypatch):
    import socket,ssl,subprocess,threading
    from src.server.mailer import send_link
    monkeypatch.setenv('FSP_SMTP_ENABLED', '1')
    cert,key=tmp_path/'smtp.crt',tmp_path/'smtp.key'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    server=socket.socket();server.bind(('127.0.0.1',0));server.listen(1);server.settimeout(10)
    port=server.getsockname()[1];messages=[];errors=[]
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
    def sink():
        try:
            with server:
                raw,_=server.accept()
                with context.wrap_socket(raw,server_side=True) as connection:
                    stream=connection.makefile('rwb');stream.write(b'220 localhost test SMTP\r\n');stream.flush()
                    while line:=stream.readline():
                        command=line.split(b' ',1)[0].strip().upper()
                        if command==b'DATA':
                            stream.write(b'354 send message\r\n');stream.flush();parts=[]
                            while (part:=stream.readline())!=b'.\r\n':
                                if not part:raise RuntimeError('Incomplete test SMTP message')
                                parts.append(part)
                            messages.append(b''.join(parts));stream.write(b'250 accepted\r\n')
                        elif command==b'QUIT':stream.write(b'221 bye\r\n');stream.flush();break
                        else:stream.write(b'250 OK\r\n')
                        stream.flush()
        except Exception as error:errors.append(type(error).__name__)
    thread=threading.Thread(target=sink,daemon=True);thread.start()
    monkeypatch.setenv('FSP_SMTP_HOST','127.0.0.1');monkeypatch.setenv('FSP_SMTP_PORT',str(port));monkeypatch.setenv('FSP_SMTP_TLS','ssl');monkeypatch.delenv('FSP_SMTP_USER',raising=False)
    original=ssl.create_default_context
    monkeypatch.setattr(ssl,'create_default_context',lambda:original(cafile=str(cert)))
    assert send_link('smtp-test@example.invalid',secrets.token_urlsafe(24))=='smtp'
    thread.join(10);assert not thread.is_alive() and not errors and len(messages)==1
    assert b'To: smtp-test@example.invalid' in messages[0]

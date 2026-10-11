"""Заявленный стек не присваивает категорию; задачи сохраняют фильтры и snapshot."""
from copy import deepcopy
from tests.test_api import client, login, register
from src.server.models import Attempt, Profile, Search
from src.server.assessment import VERSION
from src.server import app as server_app
from tests.test_api import invite


def search(client, **changes):
    query=dict(specialization='backend', grade='junior', must_skills=['python'],
               desired_skills=[], salary_to=200000, format='remote', fsp_only=False,
               work_tasks=[])
    return client.post('/api/v1/company/searches', json={**query, **changes})


def test_invitation_views_do_not_fetch_unused_skill_history(client, monkeypatch):
    # В длинных списках предложений нужен alias, а не полный профиль с историей.
    # Запросы оценки/практики на каждое предложение увеличивали задержку действий.
    def unexpected_history(*args):
        raise AssertionError('Invitation projection must not load skill history')
    monkeypatch.setattr(server_app, 'skill_evidence', unexpected_history)
    login(client, 'employer-x')
    sent = invite(client, key='alias-without-skill-history')
    assert sent.status_code == 201 and sent.json()['candidate_alias'] == 'P-104'
    assert client.get('/api/v1/company/invitations').status_code == 200
    login(client, 'candidate-a')
    incoming = client.get('/api/v1/candidate/invitations')
    assert incoming.status_code == 200
    viewed = client.post('/api/v1/candidate/invitations/'+sent.json()['id']+'/view')
    assert viewed.status_code == 200 and viewed.json()['status'] == 'viewed'
    applied = client.post('/api/v1/candidate/vacancies/demo-vacancy-backend/apply')
    assert applied.status_code == 201 and applied.json()['candidate_alias'] == 'P-104'
    assert client.get('/api/v1/candidate/applications').status_code == 200
    task = client.get('/api/v1/candidate/tasks').json()['available'][0]
    submitted = client.post('/api/v1/candidate/tasks/'+task['id']+'/submit',
                            json={'answer':'Синтетический ответ для проверки адресного доступа.'})
    assert submitted.status_code == 201 and submitted.json()['candidate_alias'] == 'P-104'
    assert client.get('/api/v1/candidate/tasks').status_code == 200
    assert client.post('/api/v1/candidate/applications/'+applied.json()['id']+'/withdraw').status_code == 200
    login(client, 'employer-x')
    assert client.get('/api/v1/company/applications').status_code == 200
    assert client.get('/api/v1/company/task-responses').status_code == 200


def test_declared_skills_save_but_do_not_confirm_or_publish(client):
    register(client, name='declared-only')
    own=client.get('/api/v1/candidate/profile').json()
    body={key: own[key] for key in ('industry','specialization','claimed_grade','salary_min','formats','contact','resume')}
    body['resume']['declared_skills']=['python','http','react','python']
    assert client.put('/api/v1/candidate/profile',json=body).status_code==200
    updated=client.get('/api/v1/candidate/profile').json()
    assert updated['skill_evidence']['declared']==['python','http','react']
    assert updated['skill_evidence']['assessment']==[] and updated['skills']==[]
    assert updated['confirmed_grade'] is None and not updated['published']
    body['resume']['declared_skills']=['person@example.invalid']
    assert client.put('/api/v1/candidate/profile',json=body).status_code==422


def test_actual_snapshot_evidence_and_private_form_allowlist(client):
    register(client, name='evidence-snapshot')
    started=client.post('/api/v1/assessments/attempts',json=dict(specialization='backend',grade='junior')).json()
    assert started['version']==VERSION=='scenarios-v6'
    assert all(not {'answer','explanation','topic','solution'}&q.keys() for q in started['questions'])
    with client.app.state.factory() as db:
        form=deepcopy(db.get(Attempt,started['id']).question_form)
    answers={q['id']:q['answer'] for q in form}
    result=client.post('/api/v1/assessments/attempts/'+started['id']+'/submit',json={'answers':answers})
    assert result.status_code==200 and result.json()['score']==100
    own=client.get('/api/v1/candidate/profile').json()
    evidence=own['skill_evidence']['assessment']
    assert len(evidence)==3 and all(row['source']=='assessment' and row['version']==VERSION and row['correct']==row['total']==4 for row in evidence)
    assert 'answer' not in repr(own['skill_evidence']) and 'explanation' not in repr(own['skill_evidence'])


def test_task_mapping_only_desired_and_never_self_claimed(client):
    with client.app.state.factory() as db:
        a=db.get(Profile,'demo-candidate-a');b=db.get(Profile,'demo-candidate-b')
        a.skills=['python'];b.skills=['python','http']
        a.test_score=b.test_score=80;a.fsp_signal=b.fsp_signal=0
        a.assessed_at=b.assessed_at=None;a.activity_at=b.activity_at=None
        a.resume={**a.resume,'declared_skills':['http','react']}
        db.commit()
    login(client,'employer-x')
    baseline=search(client).json()
    assert baseline['candidate_ids']==['demo-candidate-a','demo-candidate-b']
    response=search(client,work_tasks=['api-development'])
    assert response.status_code==201
    matched=response.json()
    assert matched['candidate_ids']==['demo-candidate-b','demo-candidate-a']
    assert matched['algorithm_version']=='weighted-v1+team-work-v1'
    a=next(row for row in matched['rows'] if row['id']=='demo-candidate-a')
    assert a['work_matches'][0]['missing_skills']==['http'] and a['work_matches'][0]['status']=='partial'
    assert a['components']['skills']==17.5 and a['skill_evidence']['declared']==['http','react']
    assert 'contact' not in a and 'resume' not in a
    strict=search(client,must_skills=['python','http'],work_tasks=['api-development']).json()
    assert strict['candidate_ids']==['demo-candidate-b']
    assert search(client,work_tasks=['ui-accessibility']).status_code==422


def test_task_search_and_need_preserve_original_query_and_history(client):
    login(client,'employer-x')
    response=search(client,work_tasks=['api-development']).json()
    with client.app.state.factory() as db:
        saved=db.get(Search,response['id'])
        assert saved.query['desired_skills']==[] and saved.query['work_tasks']==['api-development']
        before=deepcopy(saved.explanations)
        db.get(Profile,'demo-candidate-a').skills=['python']
        db.commit()
    restored=client.get('/api/v1/company/searches/'+response['id']).json()
    assert restored['rows']==before
    query=restored['query']
    need=client.post('/api/v1/company/needs',json={**query,'title':'API команды','description':'Синтетическая потребность на разработку API команды.'})
    assert need.status_code==201 and need.json()['query']['work_tasks']==['api-development']
    login(client,'employer-y')
    assert client.get('/api/v1/company/searches/'+response['id']).status_code==404


def test_legacy_search_without_new_evidence_remains_readable(client):
    login(client,'employer-x')
    saved=search(client).json()
    with client.app.state.factory() as db:
        obj=db.get(Search,saved['id'])
        obj.explanations=[{k:v for k,v in row.items() if k not in {'skill_evidence','work_matches'}} for row in obj.explanations]
        obj.query={k:v for k,v in obj.query.items() if k!='work_tasks'}
        db.commit()
    assert client.get('/api/v1/company/searches/'+saved['id']).status_code==200

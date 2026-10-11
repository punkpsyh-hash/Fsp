"""Регрессия черновиков, неизменяемых объяснений и распознавания резюме."""
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch
from sqlalchemy import select
from test_api import client, login, register
from src.server.models import Attempt, Profile, now
from src.server.assessment import questions


def test_attempt_draft_reload_conflict_ownership_and_immutable_form(client):
    register(client,'saved-form')
    attempt=client.post('/api/v1/assessments/attempts',json={'grade':'junior'}).json()
    path='/api/v1/assessments/attempts/'+attempt['id']
    assert attempt['revision']==0 and attempt['answers']=={}
    q=attempt['questions'][0]
    draft={q['id']:q['options'][0]}
    saved=client.put(path+'/draft',json={'answers':draft,'expected_revision':0})
    assert saved.status_code==200 and saved.json()['revision']==1
    assert client.get('/api/v1/candidate/active-assessment').json()['answers']==draft
    assert client.put(path+'/draft',json={'answers':{},'expected_revision':0}).status_code==409
    assert client.get(path).json()['answers']==draft
    assert client.put(path+'/draft',json={'answers':{'alien':'answer'},'expected_revision':1}).status_code==422
    # Даже изменённый генератор не меняет уже выданную форму и серверные ключи.
    with patch('src.server.app.questions',side_effect=AssertionError('generator called')):
        reloaded=client.get(path)
        assert reloaded.status_code==200 and reloaded.json()['questions']==attempt['questions']
    assert all('answer' not in item for item in reloaded.json()['questions'])
    login(client,'candidate-b')
    assert client.get(path).status_code==404
    assert client.put(path+'/draft',json={'answers':draft,'expected_revision':1}).status_code==404


def test_expired_draft_is_retained_and_submitted_draft_is_terminal(client):
    user=register(client,'expired-form')
    first=client.post('/api/v1/assessments/attempts',json={'grade':'junior'}).json()
    with client.app.state.factory() as db:
        row=db.get(Attempt,first['id']); row.created_at=now()-timedelta(minutes=61)
        row.answers={first['questions'][0]['id']:first['questions'][0]['options'][0]}; db.commit()
    path='/api/v1/assessments/attempts/'+first['id']
    assert client.get('/api/v1/candidate/active-assessment').json() is None
    assert client.put(path+'/draft',json={'answers':{},'expected_revision':0}).status_code==409
    assert client.get(path).json()['answers']
    second=client.post('/api/v1/assessments/attempts',json={'grade':'junior'}).json()
    with client.app.state.factory() as db:
        row=db.get(Attempt,second['id']); answers={q['id']:q['answer'] for q in row.question_form}
    path='/api/v1/assessments/attempts/'+second['id']
    assert client.post(path+'/submit',json={'answers':answers}).json()['passed']
    assert client.put(path+'/draft',json={'answers':{},'expected_revision':0}).status_code==409
    assert client.get('/api/v1/candidate/active-assessment').json() is None


def test_search_preserves_historical_components_without_preserving_visibility(client):
    login(client,'employer-x')
    result=client.post('/api/v1/company/searches',json={'salary_to':200000}).json()
    assert result['rows']
    original=result['rows'][0]
    assert abs(sum(original['components'].values())-original['score'])<0.01
    with client.app.state.factory() as db:
        profile=db.get(Profile,original['id']); profile.test_score=20; profile.skills=[]; db.commit()
    path='/api/v1/company/searches/'+result['id']
    restored=client.get(path).json()
    assert restored['historical_explanation'] and restored['rows'][0]==original
    assert 'contact' not in restored['rows'][0]
    login(client,'employer-y'); assert client.get(path).status_code==404
    with client.app.state.factory() as db:
        db.get(Profile,original['id']).published=False; db.commit()
    login(client,'employer-x')
    assert original['id'] not in {r['id'] for r in client.get(path).json()['rows']}


def test_resume_preview_extracts_roles_and_soft_skills_without_confirming_them():
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from src.server.resume_parser import parse
    pdfmetrics.registerFont(TTFont('ReliabilityFont',str(__import__('pathlib').Path(__file__).resolve().parents[1]/'resources/DejaVuSans.ttf')))
    buffer=BytesIO(); writer=canvas.Canvas(buffer); writer.setFont('ReliabilityFont',12)
    lines=['ФИО: Тестовый участник','Стаж: 4 года','Роли: разработчик, team lead',
           'Стек: Python SQL Middle','Софт-навыки: коммуникация, работа в команде, планирование',
           'Образование: Тестовая программа','О себе: Синтетический пример',
           'Контакт: resume@example.invalid']
    for i,line in enumerate(lines): writer.drawString(40,800-i*22,line)
    writer.save(); result=parse(buffer.getvalue())
    assert result['resume']['roles']==['developer','team-lead']
    assert result['resume']['soft_skills']==['communication','teamwork','planning']
    assert result['resume']['years_experience']==4
    assert result['resume']['education']=='Тестовая программа'
    assert result['contact']=='resume@example.invalid' and result['claimed_grade']=='middle'
    assert 'confirmed_grade' not in result and 'confirmed_skills' not in result

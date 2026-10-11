from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from io import BytesIO
import os
from uuid import uuid4
import pytest
from jsonschema import Draft202012Validator
from pypdf import PdfReader
from fastapi.testclient import TestClient
from sqlalchemy import select
from src.server.db import database, database_url

from src.server.app import create_app
from src.server.assessment import questions
from src.server.models import Attempt, Base, LoginSession, Mail, Offer, Profile, User, now


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Быстрые функциональные fixtures явно используют демонстрационный режим;
    # strict-регрессии включают политику отдельно, рабочий API включает её сам.
    monkeypatch.setenv('FSP_INTEGRITY_ENFORCE', '0')
    admin, schema = None, None
    url = "sqlite:///"+str(tmp_path/"test.sqlite")
    if os.environ.get("FSP_TEST_POSTGRES") == "1":
        schema = "fsp_test_"+uuid4().hex
        admin, _ = database(database_url())
        with admin.begin() as conn:
            conn.exec_driver_sql('CREATE SCHEMA "'+schema+'"')
        url = database_url().update_query_dict({"options": "-csearch_path="+schema})
    app = create_app(url, demo=True)
    Base.metadata.create_all(app.state.engine)
    try:
        with TestClient(app) as client:
            original=client.request
            contract=app.openapi()
            def checked(method,url,*args,**kwargs):
                response=original(method,url,*args,**kwargs)
                if response.status_code==204 or not response.headers.get('content-type','').startswith('application/json'):
                    return response
                from starlette.routing import Match
                scope={'type':'http','path':response.request.url.path,'method':method.upper(),'root_path':''}
                route=next((r for r in app.routes if r.matches(scope)[0]==Match.FULL and getattr(r,'include_in_schema',False)),None)
                if route:
                    spec=contract['paths'][route.path][method.lower()]['responses'].get(str(response.status_code))
                    assert spec is not None,'Undocumented response status'
                    schema=spec['content']['application/json']['schema']|{'components':contract['components']}
                    validator=Draft202012Validator(schema)
                    # Не выводить весь payload/токены при ошибке схемы.
                    errors=list(validator.iter_errors(response.json()))
                    assert not errors, 'Response schema mismatch at '+str(errors[0].absolute_path) if errors else ''
                return response
            client.request=checked
            yield client
    finally:
        if admin and schema:
            with admin.begin() as conn:
                conn.exec_driver_sql('DROP SCHEMA "'+schema+'" CASCADE')
            admin.dispose()


def login(client, key):
    r = client.post("/api/v1/auth/demo-login", json={"user_id": "demo-"+key})
    assert r.status_code == 200
    client.headers["X-CSRF-Token"] = r.json()["csrf"]
    return r.json()


def invite(client, key="test-key-123", candidate="demo-candidate-a", **changes):
    body = dict(candidate_id=candidate, description="Синтетическое предложение Python и SQL", salary_from=100000, salary_to=150000, salary_basis="gross")
    body.update(changes)
    return client.post("/api/v1/company/invitations", json=body, headers={"Idempotency-Key": key})


def register(client, name="new-candidate", role="candidate"):
    email = name+"@example.invalid"
    r = client.post("/api/v1/auth/register", json={"email":email,"role":role,"label":"Синтетический профиль","consent":True})
    assert r.status_code == 201, r.text
    mail = next(m for m in client.get("/api/v1/auth/mock-mail").json() if m["email"] == email)
    r = client.post("/api/v1/auth/verify", json={"token": mail["token"]})
    assert r.status_code == 200
    client.headers["X-CSRF-Token"] = r.json()["csrf"]
    return r.json()


def test_identity_csrf_origin_and_cookie(client):
    assert client.get("/api/v1/candidate/profile").status_code == 401
    login(client,"employer-x")
    assert client.get("/api/v1/candidate/profile").status_code == 403
    client.headers.pop("X-CSRF-Token")
    assert invite(client).status_code == 403
    assert client.post("/api/v1/auth/demo-login",json={"user_id":"demo-employer-x"},headers={"Origin":"https://outside.invalid"}).status_code == 403
    r=client.post("/api/v1/auth/demo-login",json={"user_id":"demo-employer-x"},headers={"Origin":"http://127.0.0.1:5173"})
    assert r.status_code==200
    assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=strict" in r.headers["set-cookie"]


def test_full_contact_workflow_owner_and_company_boundaries(client):
    login(client,"employer-x")
    r=invite(client);assert r.status_code==201
    offer=r.json();assert offer["vacancy_id"] is None and "contact" not in offer
    assert "contact" not in client.get("/api/v1/company/candidates/demo-candidate-a").json()
    login(client,"candidate-b")
    assert client.post(f'/api/v1/candidate/invitations/{offer["id"]}/decision',json={"decision":"accepted"}).status_code==404
    assert client.get("/api/v1/candidate/invitations").json()==[]
    login(client,"candidate-a")
    path=f'/api/v1/candidate/invitations/{offer["id"]}/decision'
    assert client.post(path,json={"decision":"accepted"}).status_code==200
    assert client.post(path,json={"decision":"accepted"}).status_code==200
    assert client.post(path,json={"decision":"declined"}).status_code==409
    login(client,"employer-y")
    assert client.get("/api/v1/company/invitations").json()==[]
    assert "contact" not in client.get("/api/v1/company/candidates/demo-candidate-a").json()
    login(client,"employer-x")
    assert client.get("/api/v1/company/candidates/demo-candidate-a").json()["contact"].endswith("@example.invalid")
    login(client,"candidate-a")
    assert client.delete("/api/v1/candidate/contacts/demo-employer-x").status_code==204
    # Повторное принятие старого приглашения не восстанавливает отозванный grant.
    assert client.post(path,json={"decision":"accepted"}).status_code==200
    login(client,"employer-x")
    assert "contact" not in client.get("/api/v1/company/candidates/demo-candidate-a").json()


def test_idempotency_and_strict_salary(client):
    login(client,"employer-x")
    first=invite(client); assert first.status_code==201
    assert invite(client).json()["id"]==first.json()["id"]
    assert invite(client,salary_to=160000).status_code==409
    for value in (True,100.5,"100",0,-1):
        assert invite(client,key="other-key-123",salary_from=value).status_code==422
    assert invite(client,key="other-key-123",salary_from=200000,salary_to=150000).status_code==422


def test_decline_and_withdraw_do_not_grant_contacts(client):
    login(client,"employer-x")
    a=invite(client).json();b=invite(client,key="second-key-123").json()
    assert client.post(f'/api/v1/company/invitations/{b["id"]}/withdraw').status_code==200
    login(client,"candidate-a")
    assert client.post(f'/api/v1/candidate/invitations/{a["id"]}/decision',json={"decision":"declined"}).status_code==200
    assert client.post(f'/api/v1/candidate/invitations/{b["id"]}/decision',json={"decision":"accepted"}).status_code==409
    login(client,"employer-x")
    assert all("contact" not in o for o in client.get("/api/v1/company/invitations").json())


def test_expiration_boundary(client):
    login(client,"employer-x");offer=invite(client).json()
    with client.app.state.factory() as db:
        db.get(Offer,offer["id"]).expires_at=now()-timedelta(seconds=1);db.commit()
    login(client,"candidate-a")
    assert client.get("/api/v1/candidate/invitations").json()[0]["status"]=="expired"
    assert client.post(f'/api/v1/candidate/invitations/{offer["id"]}/decision',json={"decision":"accepted"}).status_code==409


def test_search_privacy_filters_snapshot_shortlist(client):
    login(client,"employer-x")
    query={"grade":"junior","salary_to":150000,"format":"remote","must_skills":["python"]}
    result=client.post("/api/v1/company/searches",json=query).json()
    assert result["candidate_ids"]==["demo-candidate-a","demo-candidate-b"]
    assert "example.invalid" not in str(result) and all("contact" not in r for r in result["rows"])
    assert client.put("/api/v1/company/shortlist/demo-candidate-a").status_code==204
    assert len(client.get("/api/v1/company/searches").json())==1
    login(client,"employer-y")
    assert client.get("/api/v1/company/shortlist").json()==[]
    assert client.get("/api/v1/company/searches").json()==[]
    login(client,"candidate-a")
    assert client.post("/api/v1/candidate/consents",json={"published":False}).status_code==200
    login(client,"employer-x")
    assert client.get("/api/v1/company/shortlist").json()==[]
    assert client.get("/api/v1/company/candidates/demo-candidate-a").status_code==404
    assert client.post("/api/v1/company/searches",json=query).json()["candidate_ids"]==["demo-candidate-b"]
    assert client.post("/api/v1/company/searches",json={**query,"salary_to":1}).json()["rows"]==[]


def test_registration_verification_one_time_and_no_real_emails(client):
    assert client.post("/api/v1/auth/register",json={"email":"real@example.com","role":"candidate","label":"Демо","consent":True}).status_code==422
    r=client.post("/api/v1/auth/register",json={"email":"test@example.invalid","role":"candidate","label":"Демо","consent":True});assert r.status_code==201
    assert client.post("/api/v1/auth/register",json={"email":"test@example.invalid","role":"candidate","label":"Демо","consent":True}).status_code==409
    token=client.get("/api/v1/auth/mock-mail").json()[0]["token"]
    assert client.post("/api/v1/auth/verify",json={"token":token}).status_code==200
    assert client.post("/api/v1/auth/verify",json={"token":token}).status_code==409
    with client.app.state.factory() as db:
        assert db.scalar(select(Mail)).token=="consumed"


def test_login_link_expiry(client):
    client.post("/api/v1/auth/login",json={"email":"demo-candidate-a@example.invalid"})
    token=client.get("/api/v1/auth/mock-mail").json()[0]["token"]
    with client.app.state.factory() as db:
        db.scalar(select(Mail)).expires_at=now()-timedelta(seconds=1);db.commit()
    assert client.post("/api/v1/auth/verify",json={"token":token}).status_code==409


def test_server_assessment_owner_scoring_publication_and_cooldowns(client):
    user=register(client)
    assert client.post("/api/v1/candidate/consents",json={"published":True}).status_code==409
    attempt=client.post("/api/v1/assessments/attempts",json={"grade":"junior"}).json()
    assert all("answer" not in q for q in attempt["questions"])
    with client.app.state.factory() as db:
        stored=db.get(Attempt,attempt["id"])
        answers={q["id"]:q["answer"] for q in stored.question_form}
    result=client.post(f'/api/v1/assessments/attempts/{attempt["id"]}/submit',json={"answers":answers}).json()
    assert result["score"]==100 and result["passed"] and result["demo"]
    assert client.post(f'/api/v1/assessments/attempts/{attempt["id"]}/submit',json={"answers":{}}).json()==result
    assert client.post("/api/v1/assessments/attempts",json={"grade":"junior"}).status_code==409
    assert client.post("/api/v1/assessments/attempts",json={"grade":"middle"}).status_code==409
    assert client.post("/api/v1/candidate/consents",json={"published":True}).status_code==200
    login(client,"candidate-b")
    assert client.get(f'/api/v1/assessments/attempts/{attempt["id"]}').status_code==404
    assert client.post(f'/api/v1/assessments/attempts/{attempt["id"]}/submit',json={"answers":answers}).status_code==404


def test_failed_assessment_does_not_downgrade_and_rejects_forged_score(client):
    login(client,"candidate-a")
    attempt=client.post("/api/v1/assessments/attempts",json={"grade":"junior"}).json()
    path=f'/api/v1/assessments/attempts/{attempt["id"]}/submit'
    assert client.post(path,json={"answers":{},"score":100}).status_code==422
    assert not client.post(path,json={"answers":{}}).json()["passed"]
    assert client.get("/api/v1/candidate/profile").json()["confirmed_grade"]=="junior"


def test_pdf_is_real_and_respects_projection(client):
    login(client,"employer-x")
    r=client.get("/api/v1/company/candidates/demo-candidate-a/profile.pdf")
    assert r.status_code==200 and r.content.startswith(b"%PDF")
    assert "demo-candidate-a@example.invalid" not in "".join(p.extract_text() for p in PdfReader(BytesIO(r.content)).pages)
    offer=invite(client).json()
    login(client,"candidate-a")
    own=client.get("/api/v1/candidate/profile.pdf")
    assert own.content.startswith(b"%PDF")
    assert "demo-candidate-a@example.invalid" in "".join(p.extract_text() for p in PdfReader(BytesIO(own.content)).pages)
    client.post(f'/api/v1/candidate/invitations/{offer["id"]}/decision',json={"decision":"accepted"})
    login(client,"employer-x")
    permitted=client.get("/api/v1/company/candidates/demo-candidate-a/profile.pdf")
    assert "demo-candidate-a@example.invalid" in "".join(p.extract_text() for p in PdfReader(BytesIO(permitted.content)).pages)
    login(client,"employer-y")
    forbidden=client.get("/api/v1/company/candidates/demo-candidate-a/profile.pdf")
    assert "demo-candidate-a@example.invalid" not in "".join(p.extract_text() for p in PdfReader(BytesIO(forbidden.content)).pages)


def test_session_expiry_and_logout(client):
    login(client,"candidate-a")
    token=client.cookies.get("fsp_session")
    with client.app.state.factory() as db:
        db.get(LoginSession,sha256(token.encode()).hexdigest()).expires_at=now()-timedelta(seconds=1);db.commit()
    assert client.get("/api/v1/me").status_code==401
    login(client,"candidate-a")
    assert client.post("/api/v1/auth/logout").status_code==204
    assert client.get("/api/v1/me").status_code==401


def test_production_is_fail_closed(tmp_path):
    app=create_app("sqlite:///"+str(tmp_path/"closed.sqlite"),demo=False)
    with pytest.raises(RuntimeError,match="Публичный запуск запрещён"):
        with TestClient(app):
            pass


def test_hosted_profile_has_no_open_mail_sink_or_passwordless_login(client, monkeypatch):
    # FSP_SMTP_HOST включает режим размещённого стенда: токены не хранятся и не отдаются.
    monkeypatch.setenv("FSP_SMTP_HOST", "smtp.invalid")
    monkeypatch.setattr("src.server.app.send_link", lambda email, token: "smtp")
    r = client.post("/api/v1/auth/register", json=dict(email="hosted@example.invalid", role="candidate", label="Hosted", consent=True))
    assert r.status_code == 201, r.text
    assert client.get("/api/v1/auth/mock-mail").status_code == 404
    with client.app.state.factory() as db:
        assert all(m.token == "hidden" for m in db.query(Mail).all() if m.user_id == db.query(User).filter_by(email="hosted@example.invalid").one().id)
    monkeypatch.setenv("FSP_DEMO_LOGIN", "0")
    assert client.get("/api/v1/auth/demo-accounts").status_code == 404
    assert client.post("/api/v1/auth/demo-login", json={"user_id": "candidate-a"}).status_code == 404

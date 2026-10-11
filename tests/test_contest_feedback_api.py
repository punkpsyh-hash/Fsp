"""Разбор завершённой формы: доступ владельца, отсутствие утечки и сохранение истории."""
from copy import deepcopy
from datetime import timedelta

from tests.test_api import client, login, register
from src.server.models import Attempt, now
from src.server.bank_examples import seed_banks
from src.server.bank_models import TaskBank, BankVersion


def start(client):
    register(client, name="feedback-candidate")
    response = client.post("/api/v1/assessments/attempts", json={"specialization": "backend", "grade": "junior"})
    assert response.status_code == 201
    return response.json()


def test_feedback_not_exposed_in_active_draft_or_expired_attempt(client):
    attempt = start(client)
    assert attempt["feedback"] is None
    assert all("answer" not in question for question in attempt["questions"])
    path = "/api/v1/assessments/attempts/" + attempt["id"]
    draft = client.put(path + "/draft", json={"answers": {}, "expected_revision": 0})
    assert draft.status_code == 200 and draft.json()["feedback"] is None
    assert client.get("/api/v1/candidate/active-assessment").json()["feedback"] is None
    with client.app.state.factory() as db:
        db.get(Attempt, attempt["id"]).created_at = now() - timedelta(minutes=61)
        db.commit()
    assert client.get(path).json()["feedback"] is None


def test_completed_feedback_uses_authoritative_form_without_changing_result(client):
    attempt = start(client)
    with client.app.state.factory() as db:
        saved = db.get(Attempt, attempt["id"])
        snapshot = deepcopy(saved.question_form)
    answers = {q["id"]: q["answer"] for q in snapshot}
    first = snapshot[0]
    answers[first["id"]] = next(value for value in first["options"] if value != first["answer"])
    path = "/api/v1/assessments/attempts/" + attempt["id"]
    submitted = client.post(path + "/submit", json={"answers": answers})
    assert submitted.status_code == 200
    view = client.get(path).json()
    assert view["result"] == submitted.json()
    report = view["feedback"]
    assert report["correct"] == 11 and report["total"] == 12 and report["needed_correct"] == 9
    question = next(q for q in report["questions"] if q["id"] == first["id"])
    assert question["status"] == "incorrect" and question["correct_answer"] == first["answer"]
    assert question["selected_answer"] == answers[first["id"]]
    assert all(q["explanation"] for q in report["questions"])
    assert len(report["skills"]) == 3
    with client.app.state.factory() as db:
        saved = db.get(Attempt, attempt["id"])
        saved.seed = 99999999  # Доказываем, что ключи и разбор идут из snapshot.
        db.commit()
    assert client.get(path).json()["feedback"] == report
    assert client.post(path + "/submit", json={"answers": {}}).json() == submitted.json()
    with client.app.state.factory() as db:
        saved = db.get(Attempt, attempt["id"])
        assert saved.question_form == snapshot and saved.result == submitted.json()


def test_feedback_owner_and_role_boundaries(client):
    attempt = start(client)
    path = "/api/v1/assessments/attempts/" + attempt["id"]
    with client.app.state.factory() as db:
        saved = db.get(Attempt, attempt["id"])
        answers = {q["id"]: q["answer"] for q in saved.question_form}
    assert client.post(path + "/submit", json={"answers": answers}).status_code == 200
    login(client, "candidate-b")
    assert client.get(path).status_code == 404
    login(client, "employer-x")
    assert client.get(path).status_code == 403
    client.cookies.clear()
    assert client.get(path).status_code == 401


def test_curated_practice_is_available_without_keys_and_seed_preserves_versions(client):
    login(client, "candidate-a")
    banks = client.get("/api/v1/candidate/banks").json()
    document = next(bank for bank in banks if bank["bank_id"] == "demo-practice-contest")
    assert document["grade"] == "middle" and document["scope"] == "platform"
    assert len(document["tasks"]) == 6
    assert all(not {"answer_key", "hidden_tests", "numeric_answer"} & task.keys() for task in document["tasks"])
    with client.app.state.factory() as db:
        old = db.get(BankVersion, "demo-practice-all-types-v1")
        old_hash, old_document = old.content_hash, deepcopy(old.document)
        new = db.get(BankVersion, "demo-practice-contest-v1")
        new.state = "archived"
        bank = db.get(TaskBank, "demo-practice-contest")
        bank.title = "Существующее название владельца"
        db.commit()
    seed_banks(client.app.state.factory)
    with client.app.state.factory() as db:
        assert db.get(BankVersion, "demo-practice-contest-v1").state == "archived"
        assert db.get(TaskBank, "demo-practice-contest").title == "Существующее название владельца"
        old = db.get(BankVersion, "demo-practice-all-types-v1")
        assert old.content_hash == old_hash and old.document == old_document

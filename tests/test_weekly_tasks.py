"""Недельное предложение короткого задания: отбор, период и отсутствие побочных эффектов."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from tests.test_api import client, login, register
from src.server import product
from src.server.models import Audit, EmployerTask, TaskResponse


TASKS = "/api/v1/candidate/tasks"


def create_task(client, *, title, specialization="backend", grade="junior", published=True):
    result = client.post("/api/v1/company/tasks", json={
        "title": title,
        "description": "Синтетическое задание для проверки недельного предложения кандидату.",
        "specialization": specialization,
        "grade": grade,
        "rubric": "Проверить объяснение решения, границы задачи и порядок действий.",
        "published": published,
    })
    assert result.status_code == 201, result.text
    return result.json()["id"]


def count_rows(client, model):
    with client.app.state.factory() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_weekly_offer_is_stable_for_utc_week_and_matches_published_grade(client, monkeypatch):
    login(client, "employer-x")
    matching = create_task(client, title="Дополнительная задача Backend Junior")
    draft = create_task(client, title="Неопубликованная задача", published=False)
    other_spec = create_task(client, title="Задача другой специализации", specialization="frontend")
    other_grade = create_task(client, title="Задача другого грейда", grade="middle")
    login(client, "candidate-a")
    before_profile = client.get("/api/v1/candidate/profile").json()
    before_audit = count_rows(client, Audit)
    before_responses = count_rows(client, TaskResponse)

    sunday = datetime(2026, 10, 4, 23, 59, 59, tzinfo=timezone.utc)
    monkeypatch.setattr(product, "now", lambda: sunday)
    first = client.get(TASKS)
    assert first.status_code == 200, first.text
    first = first.json()
    assert first["recommendation_state"] == "offered"
    assert first["recommendation"]["task"]["id"] in {"demo-task-backend", matching}
    assert {task["id"] for task in first["available"]} == {"demo-task-backend", matching}
    assert {draft, other_spec, other_grade}.isdisjoint(task["id"] for task in first["available"])
    assert datetime.fromisoformat(first["recommendation"]["period_starts_at"]) == datetime(2026, 9, 28, tzinfo=timezone.utc)
    assert datetime.fromisoformat(first["recommendation"]["next_period_at"]) == datetime(2026, 10, 5, tzinfo=timezone.utc)
    assert client.get(TASKS).json()["recommendation"] == first["recommendation"]

    # Снятие другого задания не должно переназначать уже предложенное в этой неделе.
    other_matching = ({"demo-task-backend", matching} - {first["recommendation"]["task"]["id"]}).pop()
    with client.app.state.factory() as db:
        db.get(EmployerTask, other_matching).published = False
        db.commit()
    assert client.get(TASKS).json()["recommendation"] == first["recommendation"]

    monday = sunday + timedelta(seconds=1)
    monkeypatch.setattr(product, "now", lambda: monday)
    next_week = client.get(TASKS).json()
    assert next_week["recommendation_state"] == "offered"
    assert datetime.fromisoformat(next_week["recommendation"]["period_starts_at"]) == monday
    assert datetime.fromisoformat(next_week["recommendation"]["next_period_at"]) == monday + timedelta(days=7)
    assert next_week["recommendation"]["id"] != first["recommendation"]["id"]
    assert next_week["recommendation"]["task"]["id"] == first["recommendation"]["task"]["id"]

    assert count_rows(client, Audit) == before_audit
    assert count_rows(client, TaskResponse) == before_responses
    after_profile = client.get("/api/v1/candidate/profile").json()
    assert (after_profile["confirmed_grade"], after_profile["test_score"], after_profile["assessed_at"]) == (
        before_profile["confirmed_grade"], before_profile["test_score"], before_profile["assessed_at"]
    )


def test_weekly_offer_waits_full_seven_days_after_response(client, monkeypatch):
    login(client, "employer-x")
    second = create_task(client, title="Вторая подходящая задача Backend Junior")
    login(client, "candidate-a")
    grade = client.get("/api/v1/candidate/profile").json()["confirmed_grade"]
    submitted = client.post("/api/v1/candidate/tasks/demo-task-backend/submit", json={
        "answer": "Проверю доступ другой компании, отзыв разрешения и повторную отправку ответа."
    })
    assert submitted.status_code == 201, submitted.text
    submitted_at = datetime(2026, 10, 5, tzinfo=timezone.utc)
    with client.app.state.factory() as db:
        response = db.get(TaskResponse, submitted.json()["id"])
        response.submitted_at = submitted_at
        db.commit()

    due = submitted_at + timedelta(days=7)
    monkeypatch.setattr(product, "now", lambda: due - timedelta(microseconds=1))
    waiting = client.get(TASKS).json()
    assert waiting["recommendation_state"] == "cooldown"
    assert waiting["recommendation"] is None and waiting["available"] == []
    assert datetime.fromisoformat(waiting["next_at"]) == due
    monkeypatch.setattr(product, "now", lambda: due)
    ready = client.get(TASKS).json()
    assert ready["recommendation_state"] == "offered"
    assert ready["recommendation"]["task"]["id"] == second
    assert {task["id"] for task in ready["available"]} == {second}
    assert client.get("/api/v1/candidate/profile").json()["confirmed_grade"] == grade


def test_unconfirmed_candidate_has_no_weekly_offer(client):
    register(client, "weekly-unconfirmed")
    result = client.get(TASKS)
    assert result.status_code == 200, result.text
    assert result.json()["recommendation_state"] == "no-grade"
    assert result.json()["recommendation"] is None
    assert result.json()["available"] == []
    assert client.get("/api/v1/candidate/profile").json()["confirmed_grade"] is None

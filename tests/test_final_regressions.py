"""Границы приватности и подтверждения двух форм после доработки 8 октября."""
from datetime import timedelta

import pytest

from src.server import integrity, app as app_module
from src.server.models import Attempt, Profile, Search, now
from tests.test_api import client, login, register  # noqa: F401
from tests.test_confirmation_stage import start, submit, answers_with_correct


def flag(client, attempt):
    response = client.post(f"/api/v1/assessments/attempts/{attempt['id']}/integrity",
                           json={"events": [{"type": "copy", "t": i * 100} for i in range(5)]})
    assert response.status_code == 202


def test_server_detects_missing_first_and_trailing_heartbeats():
    state = integrity.new_state()
    assert integrity.assess(state, 601)["level"] == "flagged"
    integrity.record_events(state, [{"type": "heartbeat", "t": 999999}], 30)
    assert integrity.assess(state, 40)["metrics"]["monitoring_gap_seconds"] == 0
    assert integrity.assess(state, 700)["level"] == "flagged"
    delayed = integrity.new_state()
    integrity.record_events(delayed, [{"type": "heartbeat", "t": 0}], 700)
    assert integrity.assess(delayed, 701)["level"] == "flagged"


def test_missing_heartbeats_hold_long_attempt_in_enforced_mode(client, monkeypatch):
    monkeypatch.setenv("FSP_INTEGRITY_ENFORCE", "1")
    register(client, "no-beat")
    attempt = start(client).json()
    with client.app.state.factory() as db:
        db.get(Attempt, attempt["id"]).created_at = now() - timedelta(minutes=11)
        db.commit()
    result = submit(client, attempt, 12)
    assert result["passed"] and not result["confirmed"] and result["integrity"]["hold"]
    assert any(s["code"] == "monitoring_gap_seconds" for s in result["integrity"]["signals"])


def test_flagged_demo_confirmation_has_valid_public_profile_and_search(client):
    register(client, "public-flag")
    attempt = start(client).json()
    flag(client, attempt)
    assert submit(client, attempt, 12)["integrity"]["level"] == "flagged"
    own = client.get("/api/v1/candidate/profile").json()
    assert own["integrity_level"] == "review"
    assert client.post("/api/v1/candidate/consents", json={"published": True}).status_code == 200
    login(client, "employer-x")
    search = client.post("/api/v1/company/searches", json={"salary_to": 200000}).json()
    row = next(r for r in search["rows"] if r["id"] == own["id"])
    assert row["integrity_level"] == "review"


def test_integrity_belongs_to_confirmed_specialization(client):
    login(client, "candidate-a")
    with client.app.state.factory() as db:
        db.get(Profile, "demo-candidate-a").integrity_level = "review"
        db.commit()
    def switch(specialization):
        return client.put("/api/v1/candidate/profile", json={
            "specialization": specialization, "claimed_grade": "junior", "salary_min": 100000,
            "formats": ["remote"], "contact": "track@example.invalid"})
    assert switch("frontend").status_code == 200
    assert client.get("/api/v1/candidate/profile").json()["integrity_level"] is None
    assert switch("backend").status_code == 200
    assert client.get("/api/v1/candidate/profile").json()["integrity_level"] == "review"


def test_explanation_rechecks_current_publication(client):
    login(client, "employer-x")
    search = client.post("/api/v1/company/searches", json={"salary_to": 200000}).json()
    row = search["rows"][0]
    path = f"/api/v1/company/searches/{search['id']}/candidates/{row['id']}/explanation"
    assert client.post(path).status_code == 200
    with client.app.state.factory() as db:
        db.get(Profile, row["id"]).published = False
        db.commit()
    assert client.post(path).status_code == 404


def test_historical_flagged_snapshot_has_valid_contract_without_changing_scores(client):
    login(client, "employer-x")
    search = client.post("/api/v1/company/searches", json={"salary_to": 200000}).json()
    with client.app.state.factory() as db:
        saved = db.get(Search, search["id"])
        saved.explanations = [{**row, "integrity_level": "flagged"} for row in saved.explanations]
        db.commit()
    restored = client.get(f"/api/v1/company/searches/{search['id']}").json()
    assert restored["rows"][0]["integrity_level"] == "review"
    assert restored["rows"][0]["score"] == search["rows"][0]["score"]
    with client.app.state.factory() as db:
        assert db.get(Search, search["id"]).explanations[0]["integrity_level"] == "flagged"


def test_feedback_waits_for_final_confirmation_decision(client):
    register(client, "feedback-stage")
    first = start(client).json()
    submit(client, first, 9)
    path = f"/api/v1/assessments/attempts/{first['id']}"
    assert client.get(path).json()["feedback"] is None
    second = start(client).json()
    assert client.get(path).json()["feedback"] is None
    submit(client, second, 12)
    assert client.get(path).json()["feedback"] is not None


def test_expired_unfinished_confirmation_does_not_reveal_feedback(client):
    register(client, "expired-feedback-stage")
    first = start(client).json()
    submit(client, first, 9)
    with client.app.state.factory() as db:
        db.get(Attempt, first["id"]).submitted_at = now() - timedelta(hours=25)
        db.commit()
    assert client.get(f"/api/v1/assessments/attempts/{first['id']}").json()["feedback"] is None


def test_held_attempt_feedback_waits_for_clean_final_recheck(client, monkeypatch):
    monkeypatch.setenv("FSP_INTEGRITY_ENFORCE", "1")
    register(client, "held-feedback")
    first = start(client).json()
    flag(client, first)
    assert submit(client, first, 12)["integrity"]["hold"]
    path = f"/api/v1/assessments/attempts/{first['id']}"
    assert client.get(path).json()["feedback"] is None
    second = start(client).json()
    assert second["context"]["recheck_of"] == first["id"]
    # Честный повтор сохраняет ответы по одному с нормальным серверным темпом,
    # а не передаёт все эталоны мгновенной пачкой, которую теперь удерживает policy.
    clock = [now()]
    monkeypatch.setattr(app_module, "now", lambda: clock[0])
    answers, revision = {}, second["revision"]
    for index, (question_id, answer) in enumerate(answers_with_correct(client, second["id"], 12).items(), 1):
        clock[0] += timedelta(seconds=20)
        beat = client.post(f"/api/v1/assessments/attempts/{second['id']}/integrity",
                          json={"events": [{"type": "heartbeat", "t": index * 20_000}]})
        assert beat.status_code == 202
        answers[question_id] = answer
        saved = client.put(f"/api/v1/assessments/attempts/{second['id']}/draft",
                           json={"answers": answers, "expected_revision": revision})
        assert saved.status_code == 200
        revision = saved.json()["revision"]
    result = submit(client, second, 12)
    assert result["confirmed"] and result["integrity"]["level"] == "clean"
    assert client.get(path).json()["feedback"] is not None


@pytest.mark.parametrize("flagged_stage", [1, 2])
def test_combined_confirmation_cannot_ignore_flagged_form(client, monkeypatch, flagged_stage):
    monkeypatch.setenv("FSP_INTEGRITY_ENFORCE", "1")
    register(client, f"aggregate-flag-{flagged_stage}")
    first = start(client).json()
    if flagged_stage == 1:
        flag(client, first)
    submit(client, first, 9)
    second = start(client).json()
    if flagged_stage == 2:
        flag(client, second)
    result = submit(client, second, 8)  # 66,67 отдельно; среднее с 75 выше 70.
    assert result["passed"] and not result["confirmed"]
    assert result["integrity"]["level"] == "flagged" and result["integrity"]["hold"]

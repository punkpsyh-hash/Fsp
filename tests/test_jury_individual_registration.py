"""Индивидуальные синтетические аккаунты публичного jury-стенда."""
from collections import OrderedDict
from hashlib import sha256
import re

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from src.server import jury
from src.server.app import RATE_LIMIT_LEDGER_SIZE, _bounded_history, create_app
from src.server.models import Base, Company, Contact, LoginSession, Mail, Profile, User
from src.server.security import password_hash


TEST_PASSWORD = "individual-synthetic-password"
SHARED_PASSWORD = "legacy-shared-jury-password-for-tests"


def set_jury_env(monkeypatch, *, individual="1", maximum="200", registration_rate="30"):
    values = {
        "FSP_JURY_MODE": "1",
        "FSP_JURY_PASSWORD": SHARED_PASSWORD,
        "FSP_JURY_OPERATOR_NAME": "Тестовый оператор",
        "FSP_JURY_OPERATOR_CONTACT": "operator@example.org",
        "FSP_JURY_OPERATOR_CONFIRMED": "1",
        "FSP_JURY_STORAGE_COUNTRY": "RU",
        "FSP_COOKIE_SECURE": "1",
        "FSP_SMTP_ENABLED": "0",
        "FSP_SMTP_HOST": "",
        "FSP_DEMO_LOGIN": "0",
        "FSP_MOCK_MAIL": "0",
        "FSP_ALLOWED_HOSTS": "jury.example.invalid",
        "FSP_ALLOWED_ORIGINS": "https://jury.example.invalid",
        "FSP_JURY_INDIVIDUAL_REGISTRATION": individual,
        "FSP_JURY_MAX_INDIVIDUAL_ACCOUNTS": maximum,
        # Браузерная матрица создаёт несколько ролей с одного адреса; production override оставляет 5/ч.
        "FSP_JURY_REGISTRATION_RATE_LIMIT": registration_rate,
        "FSP_JURY_AUTH_RATE_LIMIT": "30",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def make_app(tmp_path, name="individual.sqlite"):
    app = create_app("sqlite:///" + str(tmp_path / name), demo=True)
    Base.metadata.create_all(app.state.engine)
    return app


@pytest.fixture
def individual_client(tmp_path, monkeypatch):
    set_jury_env(monkeypatch)
    app = make_app(tmp_path)
    with TestClient(app, base_url="https://jury.example.invalid") as client:
        yield client


def register(client, role="candidate", password=TEST_PASSWORD, **extra):
    body = {"role": role, "password": password, "consent": True, **extra}
    return client.post("/api/v1/auth/jury-register", json=body,
                       headers={"Origin": "https://jury.example.invalid"})


def test_rate_limit_ledgers_evict_oldest_unique_address():
    ledger = OrderedDict()
    for index in range(RATE_LIMIT_LEDGER_SIZE + 1):
        _bounded_history(ledger, f"address-{index}").append(float(index))
    assert len(ledger) == RATE_LIMIT_LEDGER_SIZE
    assert "address-0" not in ledger
    assert list(ledger["address-1"]) == [1.0]


def test_candidate_registration_has_generated_identity_session_and_no_mail(individual_client):
    response = register(individual_client)
    assert response.status_code == 201, response.text
    account = response.json()
    assert re.fullmatch(r"jury-[0-9a-f]{32}@example\.invalid", account["email"])
    assert account["role"] == "candidate" and account["label"].startswith("Кандидат ")
    assert "Secure" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert individual_client.get("/api/v1/me").json()["email"] == account["email"]
    assert individual_client.get("/api/v1/candidate/profile").status_code == 200
    assert individual_client.get("/api/v1/company/profile").status_code == 403
    assert individual_client.post("/api/v1/auth/logout").status_code == 403
    individual_client.headers["X-CSRF-Token"] = account["csrf"]
    assert individual_client.post("/api/v1/auth/logout").status_code == 204
    login = individual_client.post("/api/v1/auth/password-login", json={
        "email": account["email"], "password": TEST_PASSWORD,
    })
    assert login.status_code == 200 and login.json()["id"] == account["id"]
    with individual_client.app.state.factory() as db:
        user = db.get(User, account["id"])
        assert user.verified and not user.demo_seed and TEST_PASSWORD not in user.password_hash
        assert db.get(Profile, user.id) is not None
        assert db.get(Contact, user.id).value == user.email
        assert db.scalar(select(Mail)) is None


def test_public_policy_describes_individual_synthetic_access(individual_client):
    policy = individual_client.get("/legal/privacy")
    assert policy.status_code == 200
    assert "отдельный синтетический аккаунт" in policy.text
    assert "настоящая почта и имя не запрашиваются" in policy.text
    assert "Общие seed-аккаунты недоступны для входа" in policy.text
    assert "Восстановления пароля по почте нет" in policy.text
    assert "не более 200 индивидуальных аккаунтов" in policy.text


def test_employer_registration_creates_clean_company_and_role_boundary(individual_client):
    response = register(individual_client, "employer")
    assert response.status_code == 201
    account = response.json()
    assert account["label"].startswith("Работодатель ")
    assert individual_client.get("/api/v1/company/profile").status_code == 200
    assert individual_client.get("/api/v1/candidate/profile").status_code == 403
    with individual_client.app.state.factory() as db:
        company = db.get(Company, account["id"])
        assert company.name == account["label"] and company.contact == account["email"]
        assert db.get(Profile, account["id"]) is None
    individual_client.headers["X-CSRF-Token"] = account["csrf"]
    changed = individual_client.put("/api/v1/company/profile", json={
        "name": "Синтетическая команда",
        "description": "Синтетическое описание компании для конкурсного стенда.",
        "industry": "Информационные технологии",
        "contact": "changed-company@example.invalid",
    })
    assert changed.status_code == 200
    # Редактируемые label и профиль не являются маркером происхождения аккаунта.
    jury.prepare_accounts(individual_client.app.state.factory, jury.configuration())


@pytest.mark.parametrize("body", [
    {"role": "admin", "password": TEST_PASSWORD, "consent": True},
    {"role": "candidate", "password": "too-short", "consent": True},
    {"role": "candidate", "password": TEST_PASSWORD, "consent": False},
    {"role": "candidate", "password": TEST_PASSWORD, "consent": True,
     "email": "real@example.com"},
    {"role": "candidate", "password": TEST_PASSWORD, "consent": True,
     "label": "Настоящее имя"},
])
def test_registration_rejects_admin_weak_or_personal_identity_fields(individual_client, body):
    response = individual_client.post("/api/v1/auth/jury-register", json=body,
                                      headers={"Origin": "https://jury.example.invalid"})
    assert response.status_code == 422


def test_registration_rejects_foreign_origin_and_signed_in_switch(individual_client):
    foreign = individual_client.post("/api/v1/auth/jury-register", json={
        "role": "candidate", "password": TEST_PASSWORD, "consent": True,
    }, headers={"Origin": "https://outside.invalid"})
    assert foreign.status_code == 403 and foreign.json()["code"] == "origin_forbidden"
    first = register(individual_client)
    assert first.status_code == 201
    switched = register(individual_client, "employer")
    assert switched.status_code == 409
    assert individual_client.get("/api/v1/me").json()["id"] == first.json()["id"]


def test_foreign_origin_does_not_consume_registration_quota(tmp_path, monkeypatch):
    set_jury_env(monkeypatch, registration_rate="1")
    app = make_app(tmp_path, "origin-rate.sqlite")
    with TestClient(app, base_url="https://jury.example.invalid") as client:
        foreign = client.post("/api/v1/auth/jury-register", json={
            "role": "candidate", "password": TEST_PASSWORD, "consent": True,
        }, headers={"Origin": "https://outside.invalid"})
        assert foreign.status_code == 403 and foreign.json()["code"] == "origin_forbidden"
        allowed = register(client)
        assert allowed.status_code == 201, allowed.text


def test_sessions_from_two_individual_accounts_remain_isolated(individual_client):
    first = register(individual_client).json()
    first_cookie = individual_client.cookies.get("fsp_session")
    individual_client.headers["X-CSRF-Token"] = first["csrf"]
    individual_client.post("/api/v1/auth/logout")
    individual_client.headers.pop("X-CSRF-Token")
    second = register(individual_client, "employer").json()
    second_cookie = individual_client.cookies.get("fsp_session")
    assert first["id"] != second["id"] and first_cookie != second_cookie
    assert individual_client.get("/api/v1/me").json()["id"] == second["id"]
    individual_client.cookies.set("fsp_session", first_cookie, domain="jury.example.invalid", path="/api")
    # Выход удалил первую сессию; её cookie нельзя использовать для доступа ко второму аккаунту.
    assert individual_client.get("/api/v1/me").status_code == 401


def test_restart_preserves_individual_password_and_revokes_seed_access(individual_client):
    account = register(individual_client).json()
    old_seed_token = "old-shared-seed-session"
    with individual_client.app.state.factory() as db:
        individual_hash = db.get(User, account["id"]).password_hash
        seed = db.get(User, "demo-candidate-a")
        seed.password_hash = password_hash(SHARED_PASSWORD)
        db.add(LoginSession(token_hash=sha256(old_seed_token.encode()).hexdigest(), user_id=seed.id,
                            csrf="legacy", expires_at=db.get(LoginSession, sha256(individual_client.cookies.get("fsp_session").encode()).hexdigest()).expires_at))
        db.commit()
    jury.prepare_accounts(individual_client.app.state.factory, jury.configuration())
    with individual_client.app.state.factory() as db:
        assert db.get(User, account["id"]).password_hash == individual_hash
        assert db.get(User, "demo-candidate-a").password_hash is None
        assert db.get(LoginSession, sha256(old_seed_token.encode()).hexdigest()) is None
    seed_login = individual_client.post("/api/v1/auth/password-login", json={
        "email": "demo-candidate-a@example.invalid", "password": SHARED_PASSWORD,
    })
    assert seed_login.status_code == 401 and seed_login.json()["message"] == "Неверный адрес или пароль"


def test_prepare_accounts_rejects_unmarked_or_malformed_users(individual_client):
    with individual_client.app.state.factory() as db:
        db.add(User(id="unexpected", email="unexpected@example.invalid", role="candidate",
                    label="Синтетический", verified=True, password_hash=password_hash(TEST_PASSWORD)))
        db.commit()
    with pytest.raises(RuntimeError, match="некорректный индивидуальный"):
        jury.prepare_accounts(individual_client.app.state.factory, jury.configuration())


def test_account_cap_and_registration_rate_are_enforced(tmp_path, monkeypatch):
    set_jury_env(monkeypatch, maximum="1", registration_rate="30")
    app = make_app(tmp_path, "cap.sqlite")
    with TestClient(app, base_url="https://jury.example.invalid") as client:
        first = register(client)
        client.headers["X-CSRF-Token"] = first.json()["csrf"]
        client.post("/api/v1/auth/logout")
        client.headers.pop("X-CSRF-Token")
        capped = register(client, "employer")
        assert capped.status_code == 429 and capped.headers["Retry-After"] == "3600"

    set_jury_env(monkeypatch, maximum="200", registration_rate="1")
    app = make_app(tmp_path, "rate.sqlite")
    with TestClient(app, base_url="https://jury.example.invalid") as client:
        assert register(client).status_code == 201
        client.cookies.clear()
        limited = register(client, "employer")
        assert limited.status_code == 429 and limited.headers["Retry-After"] == "3600"


def test_route_is_absent_outside_opt_in(tmp_path, monkeypatch):
    set_jury_env(monkeypatch, individual="0")
    app = make_app(tmp_path, "closed.sqlite")
    with TestClient(app, base_url="https://jury.example.invalid") as client:
        assert client.post("/api/v1/auth/jury-register", content=b"not-json").status_code == 404
        assert client.get("/api/health").json()["auth_mode"] == "shared-password"

    monkeypatch.setenv("FSP_JURY_MODE", "0")
    local = make_app(tmp_path, "local.sqlite")
    with TestClient(local) as client:
        assert client.post("/api/v1/auth/jury-register", content=b"not-json").status_code == 404
        assert client.get("/api/health").json()["auth_mode"] == "local"


@pytest.mark.parametrize(("key", "value"), [
    ("FSP_JURY_INDIVIDUAL_REGISTRATION", "yes"),
    ("FSP_JURY_MAX_INDIVIDUAL_ACCOUNTS", "0"),
    ("FSP_JURY_MAX_INDIVIDUAL_ACCOUNTS", "201"),
    ("FSP_JURY_REGISTRATION_RATE_LIMIT", "0"),
    ("FSP_JURY_REGISTRATION_RATE_LIMIT", "61"),
    ("FSP_JURY_AUTH_RATE_LIMIT", "0"),
    ("FSP_JURY_AUTH_RATE_LIMIT", "61"),
])
def test_individual_configuration_fails_closed(monkeypatch, key, value):
    set_jury_env(monkeypatch)
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError):
        jury.configuration()

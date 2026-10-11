"""PostgreSQL-границы индивидуальной регистрации jury-стенда."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from hashlib import sha256
import os
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from src.server import jury
from src.server.app import create_app
from src.server.db import database, database_url
from src.server.models import Base, Company, Contact, LoginSession, Mail, Profile, User, now
from src.server.security import password_hash


pytestmark = pytest.mark.skipif(
    os.environ.get("FSP_TEST_POSTGRES") != "1",
    reason="Требуется отдельный PostgreSQL-прогон",
)

TEST_PASSWORD = "individual-synthetic-password"
SHARED_PASSWORD = "legacy-shared-jury-password-for-tests"
ORIGIN = "https://jury.example.invalid"


def set_jury_env(monkeypatch, *, maximum="200"):
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
        "FSP_ALLOWED_ORIGINS": ORIGIN,
        "FSP_JURY_INDIVIDUAL_REGISTRATION": "1",
        "FSP_JURY_MAX_INDIVIDUAL_ACCOUNTS": maximum,
        "FSP_JURY_REGISTRATION_RATE_LIMIT": "30",
        "FSP_JURY_AUTH_RATE_LIMIT": "30",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


@contextmanager
def isolated_postgres_app(monkeypatch, *, maximum="200"):
    set_jury_env(monkeypatch, maximum=maximum)
    schema = "fsp_jury_individual_" + uuid4().hex
    admin, _ = database(database_url())
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    app = None
    try:
        url = database_url().update_query_dict({"options": "-csearch_path=" + schema})
        app = create_app(url, demo=True)
        Base.metadata.create_all(app.state.engine)
        yield app
    finally:
        if app is not None:
            app.state.engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def register(client, role="candidate"):
    return client.post("/api/v1/auth/jury-register", json={
        "role": role,
        "password": TEST_PASSWORD,
        "consent": True,
    }, headers={"Origin": ORIGIN})


def test_postgres_registers_both_roles_with_isolated_data(monkeypatch):
    with isolated_postgres_app(monkeypatch) as app:
        with TestClient(app, base_url=ORIGIN) as client:
            candidate = register(client)
            assert candidate.status_code == 201, candidate.text
            assert "Secure" in candidate.headers["set-cookie"]
            assert client.get("/api/v1/candidate/profile").status_code == 200
            assert client.get("/api/v1/company/profile").status_code == 403
            client.headers["X-CSRF-Token"] = candidate.json()["csrf"]
            assert client.post("/api/v1/auth/logout").status_code == 204
            client.headers.pop("X-CSRF-Token")

            employer = register(client, "employer")
            assert employer.status_code == 201, employer.text
            assert client.get("/api/v1/company/profile").status_code == 200
            assert client.get("/api/v1/candidate/profile").status_code == 403

            with app.state.factory() as db:
                candidate_id, employer_id = candidate.json()["id"], employer.json()["id"]
                assert db.get(Profile, candidate_id) is not None
                assert db.get(Contact, candidate_id).value == candidate.json()["email"]
                assert db.get(Company, candidate_id) is None
                assert db.get(Company, employer_id).contact == employer.json()["email"]
                assert db.get(Profile, employer_id) is None
                assert db.scalar(select(func.count()).select_from(Mail)) == 0


def test_postgres_prepare_accounts_preserves_individual_and_rejects_malformed(monkeypatch):
    with isolated_postgres_app(monkeypatch) as app:
        with TestClient(app, base_url=ORIGIN) as client:
            account = register(client).json()
            seed_token = "old-shared-seed-session-postgres"
            with app.state.factory() as db:
                individual_hash = db.get(User, account["id"]).password_hash
                seed = db.get(User, "demo-candidate-a")
                seed.password_hash = password_hash(SHARED_PASSWORD)
                db.add(LoginSession(
                    token_hash=sha256(seed_token.encode()).hexdigest(),
                    user_id=seed.id,
                    csrf="legacy",
                    expires_at=now() + timedelta(hours=1),
                ))
                db.commit()

            jury.prepare_accounts(app.state.factory, jury.configuration())
            with app.state.factory() as db:
                assert db.get(User, account["id"]).password_hash == individual_hash
                assert db.get(User, "demo-candidate-a").password_hash is None
                assert db.get(LoginSession, sha256(seed_token.encode()).hexdigest()) is None
                malformed_id = "jury-" + "a" * 32
                db.add(User(
                    id=malformed_id,
                    email=malformed_id + "@example.invalid",
                    role="candidate",
                    label="Синтетический",
                    verified=True,
                    demo_seed=False,
                    password_hash=password_hash(TEST_PASSWORD),
                ))
                db.commit()
            with pytest.raises(RuntimeError, match="некорректный индивидуальный"):
                jury.prepare_accounts(app.state.factory, jury.configuration())


def test_postgres_concurrent_cap_allows_one_account(monkeypatch):
    with isolated_postgres_app(monkeypatch, maximum="1") as app:
        with TestClient(app, base_url=ORIGIN) as first:
            second = TestClient(app, base_url=ORIGIN)
            barrier = Barrier(2)

            def create(client, role):
                barrier.wait(timeout=5)
                return register(client, role)

            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    responses = list(executor.map(create, (first, second), ("candidate", "employer")))
            finally:
                second.close()

            assert sorted(response.status_code for response in responses) == [201, 429]
            with app.state.factory() as db:
                assert db.scalar(select(func.count()).select_from(User).where(User.demo_seed.is_(False))) == 1

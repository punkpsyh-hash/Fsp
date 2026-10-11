"""Ограничение тестовых адресов действует при прямом API/SMTP-вызове."""
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.server.app import create_app
from src.server import mailer
from src.server.schemas import Email
from src.server.models import Base


REJECTED = [
    "test@gmail.com", "test@outlook.com", "test@yahoo.com", "test@icloud.com",
    "test@yandex.ru", "test@mail.ru", "test@foreign-service.ru",
    "test@example.invalid.evil.ru", "test@sub.example.invalid",
    "test@example.invalid@evil.ru", "test＠example.invalid",
    "test@еxample.invalid", "test,other@example.invalid",
    "Test <test@example.invalid>", "test:other@example.invalid",
    "test\u200b@example.invalid", "test\x00@example.invalid",
    "\r\ntest@example.invalid", "test@example.invalid\t", "test@example.invalid\x7f",
    "\u212a@example.invalid",
    "test\r\nBcc: other@example.invalid", ".test@example.invalid",
    "test..other@example.invalid", "test.@example.invalid",
    "a" * 65 + "@example.invalid",
]


@pytest.mark.parametrize("address", REJECTED)
def test_recipient_rejected_before_smtp_connection(monkeypatch, address):
    def forbidden(*args, **kwargs):
        pytest.fail("Отклонённый адрес не должен доходить до SMTP")

    monkeypatch.setenv("FSP_SMTP_HOST", "smtp.example.invalid")
    monkeypatch.setenv("FSP_SMTP_ENABLED", "1")
    monkeypatch.setattr(mailer.smtplib, "SMTP", forbidden)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", forbidden)
    with pytest.raises(ValidationError):
        mailer.send_link(address, "synthetic-code")


@pytest.mark.parametrize("address", ["TEST@example.invalid", "test.user+practice@example.invalid", "a" * 64 + "@example.invalid"])
def test_supported_synthetic_addresses_remain_usable(address):
    assert Email(email=address).email == address.lower()


@pytest.mark.parametrize("path", ["register", "login", "password-login"])
def test_direct_auth_api_rejects_foreign_and_disguised_addresses(tmp_path, monkeypatch, path):
    monkeypatch.setenv("FSP_AUTH_RATE_LIMIT", "500")
    app = create_app("sqlite:///" + str(tmp_path / "email-policy.sqlite"), demo=True)
    Base.metadata.create_all(app.state.engine)
    try:
        with TestClient(app) as client:
            for address in REJECTED:
                body = {"email": address}
                if path == "register":
                    body.update(role="candidate", label="Синтетический кандидат", consent=True)
                if path == "password-login":
                    body["password"] = "synthetic-password"
                response = client.post("/api/v1/auth/" + path, json=body)
                assert response.status_code == 422, (path, address)
    finally:
        app.state.engine.dispose()

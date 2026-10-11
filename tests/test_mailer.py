"""Сетевой транспорт не включается случайно; реальные адреса не отправляются."""
import pytest

from src.server import mailer


@pytest.fixture(autouse=True)
def clean_smtp(monkeypatch):
    for name in ('HOST', 'ENABLED', 'TLS', 'PORT', 'USER', 'PASSWORD', 'FROM'):
        monkeypatch.delenv('FSP_SMTP_' + name, raising=False)


def forbid_network(monkeypatch):
    def connect(*args, **kwargs):
        pytest.fail('Недопустимая попытка сетевого подключения')
    monkeypatch.setattr(mailer.smtplib, 'SMTP', connect)
    monkeypatch.setattr(mailer.smtplib, 'SMTP_SSL', connect)


def test_default_delivery_is_local(monkeypatch):
    forbid_network(monkeypatch)
    assert mailer.send_link('test@example.invalid', 'synthetic-code') == 'local-mailbox'


def test_configured_host_requires_explicit_enable(monkeypatch):
    forbid_network(monkeypatch)
    monkeypatch.setenv('FSP_SMTP_HOST', 'smtp.example.invalid')
    with pytest.raises(ValueError, match='Внешняя почта выключена'):
        mailer.send_link('test@example.invalid', 'synthetic-code')


@pytest.mark.parametrize('recipient', ['test@gmail.com', 'test@yandex.ru', 'test@example.invalid\nBcc: other@example.invalid'])
def test_real_or_injected_recipient_is_rejected_before_connect(monkeypatch, recipient):
    forbid_network(monkeypatch)
    monkeypatch.setenv('FSP_SMTP_ENABLED', '1')
    monkeypatch.setenv('FSP_SMTP_HOST', 'smtp.example.invalid')
    with pytest.raises(ValueError):
        mailer.send_link(recipient, 'synthetic-code')


@pytest.mark.parametrize('settings', [
    {'ENABLED': 'yes'}, {'ENABLED': '1'},
    {'ENABLED': '1', 'HOST': 'smtp.example.invalid', 'TLS': 'plain'},
    {'ENABLED': '1', 'HOST': 'smtp.example.invalid', 'PORT': '0'},
    {'ENABLED': '1', 'HOST': 'smtp.example.invalid', 'PORT': '65536'},
    {'ENABLED': '1', 'HOST': 'smtp.example.invalid', 'PORT': 'oops'},
])
def test_invalid_smtp_configuration_fails_without_network(monkeypatch, settings):
    forbid_network(monkeypatch)
    for name, value in settings.items():
        monkeypatch.setenv('FSP_SMTP_' + name, value)
    with pytest.raises(ValueError):
        mailer.send_link('test@example.invalid', 'synthetic-code')


@pytest.mark.parametrize(('mode', 'port'), [('starttls', 587), ('ssl', 465)])
def test_explicit_synthetic_delivery_uses_verified_tls(monkeypatch, mode, port):
    events = []
    class Transport:
        def __init__(self, host, connected_port, *, timeout, context=None):
            assert (host, connected_port, timeout) == ('smtp.example.invalid', port, 10)
            if mode == 'ssl':
                assert context.check_hostname and context.verify_mode == mailer.ssl.CERT_REQUIRED
            events.append('connect')
        def __enter__(self):
            return self
        def __exit__(self, *args):
            events.append('close')
        def starttls(self, *, context):
            assert context.check_hostname and context.verify_mode == mailer.ssl.CERT_REQUIRED
            events.append('tls')
        def login(self, username, password):
            assert (username, password) == ('synthetic-user', 'synthetic-password')
            events.append('login')
        def send_message(self, message):
            assert message['To'] == 'test@example.invalid'
            assert 'synthetic-code' in message.get_content()
            events.append('send')
    monkeypatch.setattr(mailer.smtplib, 'SMTP_SSL' if mode == 'ssl' else 'SMTP', Transport)
    monkeypatch.setenv('FSP_SMTP_ENABLED', '1')
    monkeypatch.setenv('FSP_SMTP_HOST', 'smtp.example.invalid')
    monkeypatch.setenv('FSP_SMTP_TLS', mode)
    monkeypatch.setenv('FSP_SMTP_USER', 'synthetic-user')
    monkeypatch.setenv('FSP_SMTP_PASSWORD', 'synthetic-password')
    assert mailer.send_link('TEST@example.invalid', 'synthetic-code') == 'smtp'
    assert events == (['connect', 'tls', 'login', 'send', 'close'] if mode == 'starttls' else ['connect', 'login', 'send', 'close'])

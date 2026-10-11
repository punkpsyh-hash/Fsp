"""Импорт не блокирует API; ресурсы разбора ограничены до обращения к parser."""
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event, Lock

import anyio
from fastapi.testclient import TestClient
import httpx
import pytest

from src.server.app import create_app
from src.server import banks
from src.server.bank_examples import example_document
from src.server.models import Base
from tests.test_api import login


PATH = '/api/v1/company/bank-imports/dry-run?filename=bank.json'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('FSP_SQLITE_POOL', '1')
    app = create_app('sqlite:///' + str(tmp_path / 'imports.sqlite'), demo=True)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as current:
        login(current, 'employer-x')
        yield current


def payload(index=0):
    document = example_document()
    document['external_id'] = 'availability-' + str(index)
    return json.dumps(document).encode()


def slow_parser(monkeypatch, count=1):
    entered, release, lock = Event(), Event(), Lock()
    original = banks.parse_import
    calls = []

    def parse(raw, filename, mapping):
        with lock:
            calls.append(raw)
            if len(calls) == count:
                entered.set()
        if not release.wait(10):
            raise RuntimeError('Test did not release parser')
        return original(raw, filename, mapping)

    monkeypatch.setattr(banks, 'parse_import', parse)
    return entered, release, calls


def test_slow_import_does_not_block_health(client, monkeypatch):
    entered, release, _ = slow_parser(monkeypatch)
    with ThreadPoolExecutor(2) as pool:
        imported = pool.submit(client.post, PATH, content=payload())
        try:
            assert entered.wait(3)
            health = pool.submit(client.get, '/api/health').result(timeout=3)
            assert health.status_code == 200
            assert not imported.done()
        finally:
            release.set()
        assert imported.result(timeout=3).status_code == 200


def test_two_imports_use_slots_and_third_is_rejected(client, monkeypatch):
    entered, release, calls = slow_parser(monkeypatch, count=2)
    with ThreadPoolExecutor(3) as pool:
        imports = [pool.submit(client.post, PATH, content=payload(i)) for i in range(2)]
        try:
            assert entered.wait(3)
            rejected = pool.submit(client.post, PATH, content=payload(2)).result(timeout=3)
            assert rejected.status_code == 429
            assert rejected.headers['Retry-After'] == '60'
            assert len(calls) == 2
        finally:
            release.set()
        assert [f.result(timeout=3).status_code for f in imports] == [200, 200]
    assert client.post(PATH, content=payload(2)).status_code == 200


def test_parser_exception_releases_slot(client, monkeypatch):
    original = banks.parse_import

    def fail(*args):
        raise RuntimeError('parser failed')

    monkeypatch.setattr(banks, 'parse_import', fail)
    # Две ошибки обнаруживают утечку обоих слотов без зависимости от деталей реализации.
    for i in range(2):
        with pytest.raises(RuntimeError, match='parser failed'):
            client.post(PATH, content=payload(i))
    monkeypatch.setattr(banks, 'parse_import', original)
    assert client.post(PATH, content=payload(2)).status_code == 200


def test_rate_limit_is_per_owner_expires_and_cache_does_not_reparse(client, monkeypatch):
    clock, calls = [100.0], []
    original = banks.parse_import
    monkeypatch.setattr(banks, 'monotonic', lambda: clock[0])

    def parse(*args):
        calls.append(args[0])
        return original(*args)

    monkeypatch.setattr(banks, 'parse_import', parse)
    first = client.post(PATH, content=payload(0)).json()
    for i in range(1, 10):
        assert client.post(PATH, content=payload(i)).status_code == 200
    rejected = client.post(PATH, content=payload(10))
    assert rejected.status_code == 429 and rejected.headers['Retry-After'] == '60'
    cached = client.post(PATH, content=payload(0))
    assert cached.status_code == 200 and cached.json()['id'] == first['id']
    assert len(calls) == 10
    login(client, 'employer-y')
    other = client.post(PATH, content=payload(0))
    assert other.status_code == 200 and other.json()['id'] != first['id']
    assert len(calls) == 11
    login(client, 'employer-x')
    clock[0] += 61
    assert client.post(PATH, content=payload(10)).status_code == 200


def test_import_role_csrf_upload_and_scope_checks_remain(client, monkeypatch):
    original = banks.parse_import
    calls = []

    def parse(*args):
        calls.append(args[0])
        return original(*args)

    monkeypatch.setattr(banks, 'parse_import', parse)
    assert client.post(PATH, content=payload(), headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    login(client, 'candidate-a')
    assert client.post(PATH, content=payload()).status_code == 403
    login(client, 'employer-y')
    assert client.post(PATH, content=b'x' * (2 * 1024 * 1024 + 1)).status_code == 413
    assert calls == []
    document = example_document()
    document['scope'] = 'platform'
    assert client.post(PATH, content=json.dumps(document).encode()).status_code == 403
    assert len(calls) == 1
    assert client.post(PATH, content=payload()).status_code == 200


def test_cancelled_request_keeps_slot_until_parser_finishes(client, monkeypatch):
    entered, release, calls = slow_parser(monkeypatch, count=2)

    async def scenario():
        headers = {'X-CSRF-Token': client.headers['X-CSRF-Token']}
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver',
                                     cookies=client.cookies, headers=headers) as browser:
            cancel = anyio.CancelScope()

            async def importing(index, cancellable=False):
                if cancellable:
                    with cancel:
                        await browser.post(PATH, content=payload(index))
                else:
                    await browser.post(PATH, content=payload(index))

            async with anyio.create_task_group() as group:
                group.start_soon(importing, 0, True)
                group.start_soon(importing, 1)
                try:
                    with anyio.fail_after(3):
                        while not entered.is_set():
                            await anyio.sleep(0.01)
                    cancel.cancel()
                    await anyio.sleep(0.05)
                    rejected = await browser.post(PATH, content=payload(2))
                    assert rejected.status_code == 429
                    assert len(calls) == 2
                finally:
                    release.set()
            assert (await browser.post(PATH, content=payload(2))).status_code == 200

    anyio.run(scenario)

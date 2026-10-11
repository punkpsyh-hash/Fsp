"""Имитация ФСП ID: OIDC code + PKCE, реестр вместо самозаявления, сигнал по результатам."""
from urllib.parse import parse_qs, urlparse

import pytest

from src.server import fsp_id
from tests.test_api import client, login  # noqa: F401  (fixture)


def authorize(client, member='FSP-1001', password='demo-1001'):
    """Проходит start → форма → authorize; возвращает (callback_url, state, code)."""
    started = client.get('/api/v1/candidate/fsp-id/start', follow_redirects=False)
    assert started.status_code == 302
    location = started.headers['location']
    state = parse_qs(urlparse(location).query)['state'][0]
    assert client.get(location).status_code == 200
    posted = client.post('/api/v1/auth/mock-fsp-id/authorize', follow_redirects=False,
                         content=f'state={state}&redirect_uri=/api/v1/candidate/fsp-id/callback&member_id={member}&password={password}',
                         headers={'Content-Type': 'application/x-www-form-urlencoded'})
    return posted, state


def link(client, member='FSP-1001', password='demo-1001'):
    posted, state = authorize(client, member, password)
    assert posted.status_code == 302, posted.text
    return client.get(posted.headers['location'], follow_redirects=False)


def profile(client):
    return client.get('/api/v1/candidate/profile').json()


def test_signal_formula_is_capped_diminishing_and_discipline_neutral():
    winner = fsp_id.events_for('FSP-1001')
    participants = fsp_id.events_for('FSP-1002')
    assert fsp_id.signal_for([]) == 0
    assert fsp_id.signal_for(winner) > fsp_id.signal_for(participants) > 0
    assert fsp_id.signal_for(participants * 10) <= 1
    # Дисциплина не влияет: те же результат и тип события дают тот же сигнал.
    other = [{**e, 'discipline': 'Робототехника'} for e in winner]
    assert fsp_id.signal_for(other) == fsp_id.signal_for(winner)
    # Командный результат весит меньше личного.
    assert fsp_id.signal_for([{'result': 'winner', 'kind': 'team'}]) < fsp_id.signal_for([{'result': 'winner', 'kind': 'individual'}])


def test_discovery_declares_pkce_and_mock(client):
    document = client.get('/api/v1/auth/mock-fsp-id/.well-known/openid-configuration').json()
    assert document['code_challenge_methods_supported'] == ['S256'] and document['mock'] is True
    assert document['token_endpoint'].endswith('/api/v1/auth/mock-fsp-id/token')


def test_full_flow_links_registry_history_and_feeds_ranking(client):
    login(client, 'candidate-a')
    assert profile(client)['fsp_state'] == 'none'
    done = link(client)
    assert done.status_code == 302 and done.headers['location'] == '/candidate/privacy?fsp=linked'
    mine = profile(client)
    assert mine['fsp_state'] == 'verified' and mine['fsp_member_id'] == 'FSP-1001'
    assert len(mine['fsp_evidence']) == 2 and all(e['source'] == 'local-mock' for e in mine['fsp_evidence'])
    login(client, 'employer-x')
    rows = client.post('/api/v1/company/searches', json={'fsp_only': True}).json()['rows']
    assert [r['id'] for r in rows] == ['demo-candidate-a']
    assert rows[0]['fsp_bonus'] == pytest.approx(10 * fsp_id.signal_for(fsp_id.events_for('FSP-1001')), abs=0.001)
    assert 'FSP-1001' not in str(rows)


def test_account_without_history_is_linked_but_empty_and_not_blocked(client):
    login(client, 'candidate-a')
    assert link(client, 'FSP-1003', 'demo-1003').headers['location'].endswith('fsp=empty')
    mine = profile(client)
    assert mine['fsp_state'] == 'linked-empty' and mine['fsp_evidence'] == []
    login(client, 'employer-x')
    assert 'demo-candidate-a' in client.post('/api/v1/company/searches', json={}).json()['candidate_ids']


def test_wrong_credentials_and_unknown_member_are_rejected_without_leaking_which(client):
    login(client, 'candidate-a')
    for member, password in (('FSP-1001', 'wrong-password'), ('FSP-9999', 'demo-1001')):
        posted, _ = authorize(client, member, password)
        assert posted.status_code == 400 and 'Неверный ФСП ID или пароль' in posted.text
    assert profile(client)['fsp_state'] == 'none'


def test_code_is_single_use_and_requires_matching_pkce_verifier(client):
    login(client, 'candidate-a')
    posted, state = authorize(client)
    code = parse_qs(urlparse(posted.headers['location']).query)['code'][0]
    body = {'grant_type': 'authorization_code', 'client_id': fsp_id.CLIENT_ID, 'code': code, 'code_verifier': 'x' * 43}
    assert client.post('/api/v1/auth/mock-fsp-id/token', json=body).status_code == 400   # неверный verifier
    assert client.get(posted.headers['location'], follow_redirects=False).headers['location'].endswith('fsp=linked')
    assert client.get(posted.headers['location'], follow_redirects=False).headers['location'].endswith('fsp=failed')  # повтор


def test_callback_requires_the_same_candidate_session(client):
    login(client, 'candidate-a')
    posted, _ = authorize(client)
    login(client, 'candidate-b')
    result = client.get(posted.headers['location'], follow_redirects=False)
    assert result.headers['location'].endswith('fsp=failed') and profile(client)['fsp_state'] == 'none'
    login(client, 'employer-x')
    assert client.get('/api/v1/candidate/fsp-id/start', follow_redirects=False).status_code == 403


def test_member_id_cannot_be_claimed_by_two_candidates(client):
    login(client, 'candidate-a')
    link(client)
    login(client, 'candidate-b')
    link(client, 'FSP-1002', 'demo-1002')
    before = profile(client)
    assert link(client).headers['location'].endswith('fsp=taken')
    after = profile(client)
    assert after['fsp_member_id'] == before['fsp_member_id'] == 'FSP-1002'
    assert after['fsp_state'] == before['fsp_state'] == 'verified'
    assert after['fsp_evidence'] == before['fsp_evidence']


def test_registry_outage_keeps_previous_history_and_unlink_clears_it(client, monkeypatch):
    login(client, 'candidate-a')
    link(client)
    monkeypatch.setenv('FSP_REGISTRY_UNAVAILABLE', '1')
    assert link(client).headers['location'].endswith('fsp=unavailable')
    mine = profile(client)
    assert mine['fsp_state'] == 'unavailable' and mine['fsp_evidence'] and mine['fsp_member_id'] == 'FSP-1001'
    removed = client.delete('/api/v1/candidate/fsp-link')
    assert removed.status_code == 200 and removed.json()['state'] == 'none' and removed.json()['signal'] == 0
    assert profile(client)['fsp_evidence'] == []


def test_authorize_page_rejects_foreign_redirect_and_escapes_parameters(client):
    login(client, 'candidate-a')
    started = client.get('/api/v1/candidate/fsp-id/start', follow_redirects=False).headers['location']
    state = parse_qs(urlparse(started).query)['state'][0]
    bad = client.get('/api/v1/auth/mock-fsp-id/authorize', params={'state': state, 'client_id': fsp_id.CLIENT_ID,
                                                                    'redirect_uri': 'https://evil.example/cb'})
    assert bad.status_code == 400
    posted = client.post('/api/v1/auth/mock-fsp-id/authorize', follow_redirects=False,
                         content=f'state={state}&redirect_uri=https://evil.example/cb&member_id=FSP-1001&password=demo-1001',
                         headers={'Content-Type': 'application/x-www-form-urlencoded'})
    assert posted.status_code == 400 and 'evil.example' not in posted.headers.get('location', '')
    page = client.get('/api/v1/auth/mock-fsp-id/authorize', params={'state': state + '"><script>', 'client_id': fsp_id.CLIENT_ID,
                                                                     'redirect_uri': '/api/v1/candidate/fsp-id/callback'})
    assert '<script>' not in page.text

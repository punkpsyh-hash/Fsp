"""Полная история подборок: границы страниц, стабильность и права доступа."""
import pytest
from tests.test_api import client, login
from src.server.models import Search, now


def seed_searches(client):
    query = dict(specialization='backend', grade='junior', must_skills=['python'],
                 desired_skills=['sql'], salary_to=200000, format='remote', fsp_only=False)
    stamp = now()
    with client.app.state.factory() as db:
        db.add_all(Search(id=f'page-search-{i:02}', company_id='demo-employer-x', query=query,
                          created_at=stamp, candidate_ids=[], explanations=[],
                          algorithm_version='weighted-v1') for i in range(23))
        db.add(Search(id='other-company-search', company_id='demo-employer-y', query=query,
                      created_at=stamp, candidate_ids=[], explanations=[],
                      algorithm_version='weighted-v1'))
        db.commit()


def test_search_history_pages_keep_all_rows_and_owner_scope(client):
    seed_searches(client)
    login(client, 'employer-x')
    rows = []
    for offset, length in ((0, 8), (8, 8), (16, 7), (24, 0)):
        response = client.get(f'/api/v1/company/searches/page?offset={offset}&limit=8')
        assert response.status_code == 200
        page = response.json()
        assert (page['total'], page['offset'], page['limit']) == (23, offset, 8)
        assert len(page['items']) == length
        assert all(set(row) == {'id', 'query', 'created_at'} for row in page['items'])
        rows.extend(row['id'] for row in page['items'])
        assert client.get(f'/api/v1/company/searches/page?offset={offset}&limit=8').json() == page
    assert rows == [f'page-search-{i:02}' for i in reversed(range(23))]
    assert len(client.get('/api/v1/company/searches').json()) == 10
    login(client, 'employer-y')
    other = client.get('/api/v1/company/searches/page').json()
    assert other['total'] == 1 and other['items'][0]['id'] == 'other-company-search'
    assert client.get('/api/v1/company/searches/page-search-00').status_code == 404
    login(client, 'candidate-a')
    assert client.get('/api/v1/company/searches/page').status_code == 403


@pytest.mark.parametrize('query', ['offset=-1', 'offset=999999999999999999999999', 'limit=0', 'limit=101', 'offset=nan', 'limit=1.5'])
def test_search_history_rejects_invalid_page_bounds(client, query):
    login(client, 'employer-x')
    assert client.get('/api/v1/company/searches/page?' + query).status_code == 422


def test_search_history_requires_session(client):
    assert client.get('/api/v1/company/searches/page').status_code == 401

"""Контроль версий, утечек ключей, атомарного импорта и серверного оценивания."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
import json
from pathlib import Path
import stat
from threading import Event
from time import monotonic, sleep
import os
import pytest
from pydantic import ValidationError
from zipfile import ZipFile, ZipInfo
from sqlalchemy import event, select
from tests.test_api import client, login
from src.server.bank_examples import example_document
from src.server.bank_imports import parse_import, csv_export
from src.server.bank_models import BankAttempt, BankCodeJob, BankVersion, TaskBank
from src.server.llm import LLMConfig
from src.server.models import Profile, now
from src.server.bank_schemas import CodeCase, CodeSubmit, Task, rubric_has_score_anchors, validate_answers


def document(code=False):
    data = example_document()
    data['external_id'] = 'test-bank'
    if not code: data['tasks'] = data['tasks'][:4]
    return data


def create_bank(client, code=False):
    login(client, 'employer-x')
    data = document(code)
    data.pop('schema_version')
    response = client.post('/api/v1/company/banks', json=data)
    assert response.status_code == 201, response.text
    return response.json()


def publish(client, bank):
    version = bank['current_version']
    response = client.post(f"/api/v1/company/banks/{bank['id']}/versions/{version['id']}/publish", json={'revision': version['revision']})
    assert response.status_code == 200, response.text
    return response.json()


def begin(client, bank, version):
    login(client, 'candidate-a')
    response = client.post(f"/api/v1/candidate/banks/{bank['id']}/attempts", json={'version_id': version['id']})
    assert response.status_code == 201, response.text
    return response.json()


def save(client, attempt, answers):
    response = client.patch('/api/v1/candidate/bank-attempts/'+attempt['id'], json={'revision': attempt['revision'], 'answers': answers})
    assert response.status_code == 200, response.text
    return response.json()


def test_draft_conflict_published_immutable_owner_and_preview(client):
    bank = create_bank(client)
    version = bank['current_version']
    payload = {key: version[key] for key in ['title', 'specialization', 'grade', 'time_limit_minutes', 'tasks', 'revision']}
    path = f"/api/v1/company/banks/{bank['id']}/versions/{version['id']}"
    first = client.patch(path, json=payload)
    assert first.status_code == 200 and first.json()['revision'] == 2
    assert client.patch(path, json=payload).status_code == 409
    published = client.post(path+'/publish', json={'revision': 2}).json()
    payload['revision'] = published['revision']
    assert client.patch(path, json=payload).status_code == 409
    preview = client.get(path+'/preview').json()
    assert 'answer_key' not in json.dumps(preview) and 'numeric_answer' not in json.dumps(preview)
    next_version = client.post(path+'/fork', json={}).json()
    assert next_version['number'] == 2 and next_version['state'] == 'draft'
    assert client.get('/api/v1/company/banks/'+bank['id']).json()['versions'][1]['tasks'] == published['tasks']
    login(client, 'employer-y')
    assert client.get('/api/v1/company/banks/'+bank['id']).status_code == 404
    assert client.get('/api/v1/company/banks/'+bank['id']+'/export').status_code == 404
    assert client.post(path+'/archive', json={}).status_code == 404


def test_publication_validation_known_skill_duplicate_keys_html(client):
    login(client, 'employer-x')
    blank = client.post('/api/v1/company/banks', json={'title': 'Пустой банк', 'tasks': []}).json()
    version = blank['current_version']
    assert client.post(f"/api/v1/company/banks/{blank['id']}/versions/{version['id']}/publish", json={'revision': 1}).status_code == 422
    data = document(); data.pop('schema_version')
    data['tasks'][0]['skills'] = ['invented-api']
    assert client.post('/api/v1/company/banks', json=data).status_code == 422
    data = document(); data.pop('schema_version'); data['tasks'][0]['prompt'] = '<script>secret</script>'
    assert client.post('/api/v1/company/banks', json=data).status_code == 422
    data = document(); data.pop('schema_version'); data['tasks'][1]['id'] = data['tasks'][0]['id']
    assert client.post('/api/v1/company/banks', json=data).status_code == 422
    data = document(); data.pop('schema_version'); data['scope'] = 'platform'
    login(client, 'employer-y')
    assert client.post('/api/v1/company/banks', json=data).status_code == 403


@pytest.mark.parametrize('invalid,field', [
    ('normalized-duplicate', 'options'),
    ('invisible-empty', 'options'),
    ('invisible-duplicate', 'options'),
    ('multiple-one-correct', 'answer_key'),
    ('multiple-all-correct', 'answer_key'),
    ('rubric-range-with-one-partial', 'rubric'),
])
def test_ambiguous_draft_is_saved_but_cannot_be_published(client, invalid, field):
    login(client, 'employer-x')
    data = document()
    data.pop('schema_version')
    if invalid == 'normalized-duplicate':
        data['tasks'][0]['options'][1]['text'] = '  ２００  '
        task_index = 0
    elif invalid == 'invisible-empty':
        data['tasks'][0]['options'][1]['text'] = '\u200b\u00ad'
        task_index = 0
    elif invalid == 'invisible-duplicate':
        data['tasks'][0]['options'][0]['text'] = '200 OK'
        data['tasks'][0]['options'][1]['text'] = '200\u200b OK'
        task_index = 0
    elif invalid == 'multiple-one-correct':
        data['tasks'][1]['answer_key'] = ['select']
        task_index = 1
    elif invalid == 'multiple-all-correct':
        data['tasks'][1]['answer_key'] = ['select', 'update', 'print']
        task_index = 1
    else:
        data['tasks'][3]['rubric'] = (
            'Оценка 0–100 баллов. 50 баллов за упоминание уникального ключа.'
        )
        task_index = 3

    created = client.post('/api/v1/company/banks', json=data)
    assert created.status_code == 201, created.text
    bank = created.json()
    version = bank['current_version']
    assert f'tasks.{task_index}.{field}' in {
        error['path'] for error in version['validation_errors']}
    response = client.post(
        f"/api/v1/company/banks/{bank['id']}/versions/{version['id']}/publish",
        json={'revision': version['revision']},
    )
    assert response.status_code == 422 and f'tasks.{task_index}.{field}' in response.text
    current = client.get('/api/v1/company/banks/' + bank['id']).json()['current_version']
    assert current['state'] == 'draft' and current['revision'] == version['revision']


def test_original_weighted_contest_rubric_remains_publishable():
    source = Path(__file__).parents[1] / 'requirements/examples/bank-contest.json'
    task = next(task for task in json.loads(source.read_text(encoding='utf-8'))['tasks']
                if task['type'] == 'open_response')
    assert rubric_has_score_anchors(task['rubric'])


def test_autosave_scoring_manual_review_never_changes_grade(client):
    bank = create_bank(client); version = publish(client, bank); attempt = begin(client, bank, version)
    profile_before = client.get('/api/v1/candidate/profile').json()
    safe = client.get('/api/v1/candidate/banks').text
    assert 'answer_key' not in safe and 'hidden_tests' not in safe and 'numeric_answer' not in safe
    saved = save(client, attempt, {'http-choice': 'ok', 'sql-choice': ['update', 'select'], 'time-number': '120 с', 'retry-open': 'Ключ и параметры привязаны к компании.'})
    assert client.patch('/api/v1/candidate/bank-attempts/'+attempt['id'], json={'revision': 1, 'answers': {}}).status_code == 409
    assert client.get('/api/v1/candidate/bank-attempts/'+attempt['id']).json()['answers'] == saved['answers']
    result = client.post('/api/v1/candidate/bank-attempts/'+attempt['id']+'/submit', json={'revision': saved['revision']}).json()
    assert result['status'] == 'pending_review' and result['result']['score'] == 75 and result['result']['pending_count'] == 1
    assert client.patch('/api/v1/candidate/bank-attempts/'+attempt['id'], json={'revision': result['revision'], 'answers': {}}).status_code == 409
    login(client, 'employer-y')
    assert client.post('/api/v1/company/bank-attempts/'+attempt['id']+'/review', json={'task_id': 'retry-open', 'score': 100, 'feedback': 'Верно'}).status_code == 404
    suggest = '/api/v1/company/bank-attempts/'+attempt['id']+'/review-suggestion'
    assert client.post(suggest, json={'task_id': 'retry-open'}).status_code == 404   # чужой автор
    login(client, 'employer-x')
    assert client.post(suggest, json={'task_id': 'http-choice'}).status_code == 422  # только открытый ответ
    assert client.post(suggest, json={'task_id': 'retry-open'}).status_code == 503   # ИИ выключен по умолчанию
    client.app.state.llm = LLMConfig(provider='mock')
    hint = client.post(suggest, json={'task_id': 'retry-open'})
    assert hint.status_code == 200 and hint.json()['review_required'] is True and 0 <= hint.json()['score'] <= 100
    assert 'review-suggestion' not in str(client.get('/api/v1/company/banks/'+bank['id']+'/attempts').json())
    review = client.post('/api/v1/company/bank-attempts/'+attempt['id']+'/review', json={'task_id': 'retry-open', 'score': 100, 'feedback': 'Верно'})
    assert review.status_code == 200 and review.json()['result']['score'] == 100
    assert client.post('/api/v1/company/bank-attempts/'+attempt['id']+'/review', json={'task_id': 'retry-open', 'score': 80, 'feedback': 'Правка'}).status_code == 409
    login(client, 'candidate-a')
    completed = client.get('/api/v1/candidate/bank-attempts/'+attempt['id']).json()
    assert completed['status'] == 'completed' and completed['result']['grade_effect'] is False
    profile_after = client.get('/api/v1/candidate/profile').json()
    assert profile_before['confirmed_grade'] == profile_after['confirmed_grade'] and profile_before['test_score'] == profile_after['test_score']
    login(client, 'candidate-b')
    assert client.get('/api/v1/candidate/bank-attempts/'+attempt['id']).status_code == 404


def test_deadline_validates_saved_answers_and_archived_attempt_continues(client):
    bank = create_bank(client); version = publish(client, bank); attempt = begin(client, bank, version)
    invalid = client.patch('/api/v1/candidate/bank-attempts/'+attempt['id'], json={'revision': 1, 'answers': {'time-number': 'NaN'}})
    assert invalid.status_code == 422
    saved = save(client, attempt, {'http-choice': 'ok'})
    with client.app.state.factory() as db:
        db.get(BankAttempt, attempt['id']).deadline = now()-timedelta(seconds=1); db.commit()
    assert client.patch('/api/v1/candidate/bank-attempts/'+attempt['id'], json={'revision': saved['revision'], 'answers': {}}).status_code == 409
    login(client, 'employer-x')
    assert client.post(f"/api/v1/company/banks/{bank['id']}/versions/{version['id']}/archive", json={}).status_code == 200
    login(client, 'candidate-a')
    final = client.post('/api/v1/candidate/bank-attempts/'+attempt['id']+'/submit', json={'revision': saved['revision']})
    assert final.status_code == 200 and final.json()['result']['score'] == 25
    assert client.post(f"/api/v1/candidate/banks/{bank['id']}/attempts", json={'version_id': version['id']}).status_code == 404


def test_json_import_atomic_idempotent_updates_draft_and_owner_export(client):
    login(client, 'employer-x')
    before = len(client.get('/api/v1/company/banks').json())
    raw = json.dumps(document()).encode()
    preview = client.post('/api/v1/company/bank-imports/dry-run?filename=tasks.json', content=raw).json()
    assert preview['valid']
    assert len(client.get('/api/v1/company/banks').json()) == before
    bank = client.post('/api/v1/company/bank-imports/'+preview['id']+'/confirm', json={}).json()
    assert bank['current_version']['state'] == 'draft'
    repeated = client.post('/api/v1/company/bank-imports/dry-run?filename=tasks.json', content=raw).json()
    assert repeated['id'] == preview['id']
    again = client.post('/api/v1/company/bank-imports/'+preview['id']+'/confirm', json={}).json()
    assert len(again['versions']) == 1 and again['id'] == bank['id']
    export = client.get('/api/v1/company/banks/'+bank['id']+'/export').json()
    assert export == document()
    exported_zip = client.get('/api/v1/company/banks/'+bank['id']+'/export?format=zip')
    assert exported_zip.status_code == 200 and exported_zip.headers['content-type'] == 'application/zip'
    parsed_zip, zip_errors, _ = parse_import(exported_zip.content, 'bank.zip')
    assert not zip_errors and parsed_zip == export
    publish(client, bank)
    revised = document(); revised['title'] = 'Изменённый набор'
    second = client.post('/api/v1/company/bank-imports/dry-run?filename=tasks.json', content=json.dumps(revised)).json()
    updated = client.post('/api/v1/company/bank-imports/'+second['id']+'/confirm', json={}).json()
    assert len(updated['versions']) == 2 and updated['versions'][0]['state'] == 'draft' and updated['versions'][1]['state'] == 'published'
    bad = client.post('/api/v1/company/bank-imports/dry-run?filename=bad.json', content=b'{"tasks":[]}').json()
    assert not bad['valid'] and client.post('/api/v1/company/bank-imports/'+bad['id']+'/confirm', json={}).status_code == 422
    login(client, 'employer-y')
    assert client.post('/api/v1/company/bank-imports/'+preview['id']+'/confirm', json={}).status_code == 404
    assert client.get('/api/v1/company/banks/'+bank['id']+'/export').status_code == 404


def test_csv_zip_limits_traversal_symlinks_duplicates_and_formulas():
    data = document(); data['tasks'] = data['tasks'][:3]
    text = csv_export(data)
    parsed, errors, _ = parse_import(text.encode(), 'tasks.csv')
    assert not errors and parsed['tasks'] == data['tasks']
    data['tasks'][0]['title'] = '=HYPERLINK("bad")'
    assert "'=HYPERLINK" in csv_export(data)
    for title in ['=SUM(A1:A2)', '+formula', '-formula', '@formula', "'=literal", "''=literal", "'plain"]:
        data['tasks'][0]['title'] = title
        restored, errors, _ = parse_import(csv_export(data).encode(), 'roundtrip.csv')
        assert not errors and restored['tasks'][0]['title'] == title
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as archive:
        package = document(True); package['tasks'][4].pop('starter_code'); package['tasks'][4]['starter_file'] = 'code/main.py'
        archive.writestr('manifest.json', json.dumps(package)); archive.writestr('code/main.py', 'print(0)')
    parsed, errors, _ = parse_import(buffer.getvalue(), 'tasks.zip')
    assert not errors and parsed['tasks'][4]['starter_code'] == 'print(0)'
    for path in ['../manifest.json', '/manifest.json', 'a\\manifest.json']:
        buffer = BytesIO()
        with ZipFile(buffer, 'w') as archive: archive.writestr(path, '{}')
        assert parse_import(buffer.getvalue(), 'bad.zip')[1]
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as archive:
        info = ZipInfo('symlink'); info.create_system = 3; info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, '../secret')
    assert parse_import(buffer.getvalue(), 'bad.zip')[1]
    assert parse_import(b'{"title":"a","title":"b"}', 'bad.json')[1]
    assert parse_import(b'x'*(2*1024*1024+1), 'bad.json')[1]


def test_csv_mapping_fixes_dry_run_and_is_part_of_idempotency(client):
    login(client, 'employer-x')
    raw = 'Код,Тип,Название,Условие,Навыки,Эталон,Лишнее\nnumber1,numeric,Секунды,Сколько секунд?,testing,120,skip\n'.encode()
    first = client.post('/api/v1/company/bank-imports/dry-run?filename=tasks.csv', content=raw).json()
    assert not first['valid']
    mapping = {'Код': 'id', 'Тип': 'type', 'Название': 'title', 'Условие': 'prompt', 'Навыки': 'skills', 'Эталон': 'numeric_answer', 'Лишнее': ''}
    preview = client.post('/api/v1/company/bank-imports/dry-run', params={'filename': 'tasks.csv', 'column_mapping': json.dumps(mapping)}, content=raw).json()
    assert preview['valid'] and preview['id'] != first['id']
    assert preview['preview']['tasks'][0]['numeric_answer'] == 120
    duplicate = client.post('/api/v1/company/bank-imports/dry-run', params={'filename': 'tasks.csv', 'column_mapping': json.dumps(mapping)}, content=raw).json()
    assert duplicate['id'] == preview['id']
    mapping['Лишнее'] = 'title'
    assert not client.post('/api/v1/company/bank-imports/dry-run', params={'filename': 'tasks.csv', 'column_mapping': json.dumps(mapping)}, content=raw).json()['valid']


def test_docx_only_extracts_text_and_requires_manual_rubric():
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="urn:w"><w:p><w:r><w:t>Синтетическое условие</w:t></w:r></w:p></w:document>')
    document, errors, warnings = parse_import(buffer.getvalue(), 'tasks.docx')
    assert not errors and warnings and document['tasks'][0]['prompt'] == 'Синтетическое условие'
    assert document['tasks'][0]['rubric'] == '' and not document['tasks'][0]['skills']


@pytest.mark.skipif(os.name == 'nt', reason='ограниченный процесс разбора PDF использует POSIX-лимиты ресурсов')
def test_pdf_text_extraction_is_a_draft_not_invented_keys():
    from reportlab.pdfgen import canvas
    buffer = BytesIO(); pdf = canvas.Canvas(buffer)
    pdf.drawString(40, 700, 'Synthetic task: describe API retries.'); pdf.save()
    document, errors, warnings = parse_import(buffer.getvalue(), 'tasks.pdf')
    assert not errors and warnings and 'Synthetic task' in document['tasks'][0]['prompt']
    assert document['tasks'][0]['answer_key'] == [] and document['tasks'][0]['rubric'] == ''


def test_code_queue_protocol_stale_lease_source_binding_and_no_hidden_leak(client, monkeypatch):
    monkeypatch.setenv('FSP_RUNNER_TOKEN', 'synthetic-runner-token-for-tests')
    bank = create_bank(client, True); version = publish(client, bank); attempt = begin(client, bank, version)
    source = 'print(14)'
    job = client.post('/api/v1/candidate/bank-attempts/'+attempt['id']+'/code-jobs', json={'task_id': 'sum-python', 'source': source}).json()
    assert job['status'] == 'queued'
    assert 'hidden_tests' not in json.dumps(job) and 'source' not in json.dumps(job)
    assert client.post('/internal/runner/claim', json={}).status_code == 403
    headers = {'Authorization': 'Bearer synthetic-runner-token-for-tests'}
    claimed = client.post('/internal/runner/claim', headers=headers, json={}).json()['job']
    assert claimed['id'] == job['id'] and claimed['source'] == source and len(claimed['tests']) == 2
    assert client.post('/internal/runner/claim', headers=headers, json={}).json()['job'] is None
    body = {'lease_token': 'invalid-token-for-test-long', 'status': 'passed', 'passed': 2, 'total': 2, 'duration_ms': 80, 'runtime_version': 'Python-test'}
    path = '/internal/runner/jobs/'+job['id']+'/result'
    assert client.post(path, headers=headers, json=body).status_code == 409
    body['lease_token'] = claimed['lease_token']; body['total'] = 1
    assert client.post(path, headers=headers, json=body).status_code == 422
    body['total'] = 2
    assert client.post(path, headers=headers, json=body).status_code == 200
    assert client.post(path, headers=headers, json=body).status_code == 409
    public = client.get('/api/v1/candidate/bank-attempts/'+attempt['id']+'/code-jobs/'+job['id']).json()
    assert public['result']['score'] == 100 and 'lease_token' not in json.dumps(public)
    saved = save(client, attempt, {'sum-python': 'print(0)'})
    final = client.post('/api/v1/candidate/bank-attempts/'+attempt['id']+'/submit', json={'revision': saved['revision']}).json()
    assert final['result']['pending_count'] == 1 and final['result']['tasks'][4]['score'] is None
    different = client.post('/internal/runner/claim', headers=headers, json={}).json()['job']
    assert different['source'] == 'print(0)'
    body['lease_token'] = different['lease_token']; body['status'] = 'wrong_answer'; body['passed'] = 0
    assert client.post('/internal/runner/jobs/'+different['id']+'/result', headers=headers, json=body).status_code == 200
    assert client.get('/api/v1/candidate/bank-attempts/'+attempt['id']).json()['result']['completed']


def test_expired_lease_retry_and_infra_error_is_pending_not_wrong(client, monkeypatch):
    monkeypatch.setenv('FSP_RUNNER_TOKEN', 'synthetic-runner-token-for-tests')
    bank = create_bank(client, True); version = publish(client, bank); attempt = begin(client, bank, version)
    saved = save(client, attempt, {'sum-python': 'print(0)', 'retry-open': 'Ключ запроса связан с компанией.'})
    client.post('/api/v1/candidate/bank-attempts/'+attempt['id']+'/submit', json={'revision': saved['revision']})
    headers = {'Authorization': 'Bearer synthetic-runner-token-for-tests'}
    claim = client.post('/internal/runner/claim', headers=headers, json={}).json()['job']
    with client.app.state.factory() as db:
        db.get(BankCodeJob, claim['id']).lease_expires_at = now()-timedelta(seconds=1); db.commit()
    retried = client.post('/internal/runner/claim', headers=headers, json={}).json()['job']
    assert retried['id'] == claim['id'] and retried['lease_token'] != claim['lease_token']
    with client.app.state.factory() as db:
        db.get(BankCodeJob, claim['id']).lease_expires_at = now()-timedelta(seconds=1); db.commit()
    login(client, 'employer-x')
    review_path = '/api/v1/company/bank-attempts/'+attempt['id']+'/review'
    review_body = {'task_id': 'retry-open', 'score': 100, 'feedback': 'Верно'}
    if client.app.state.engine.dialect.name == 'postgresql':
        # Держим настоящую review-транзакцию до commit. Expired lease обязан
        # ждать её row lock до чтения оценок, а не только перед записью result.
        from src.server import banks
        original_score = banks.score_attempt
        review_ready, release_review, expired_scoring, claim_read = (Event() for _ in range(4))
        claim_pid = []

        def paused_score(db, value):
            if not review_ready.is_set():
                review_ready.set()
                assert release_review.wait(30), 'Review barrier timed out'
            else:
                expired_scoring.set()
            return original_score(db, value)

        def observe_attempt_read(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith('SELECT') and 'FROM bank_attempts' in statement:
                claim_pid.append(conn.connection.driver_connection.info.backend_pid)
                claim_read.set()

        monkeypatch.setattr(banks, 'score_attempt', paused_score)
        with ThreadPoolExecutor(max_workers=2) as pool:
            review_future = pool.submit(client.post, review_path, json=review_body)
            try:
                assert review_ready.wait(5), 'Concurrent review did not acquire its lock'
                event.listen(client.app.state.engine, 'before_cursor_execute', observe_attempt_read)
                claim_future = pool.submit(client.post, '/internal/runner/claim', headers=headers, json={})
                assert claim_read.wait(5), 'Expired lease did not read the attempt'
                blocked = False
                deadline = monotonic()+5
                with client.app.state.engine.connect() as observer:
                    while monotonic() < deadline:
                        blocked = bool(observer.exec_driver_sql('SELECT cardinality(pg_blocking_pids(%s))', (claim_pid[0],)).scalar())
                        if blocked: break
                        sleep(0.02)
                assert blocked, 'Expired lease must wait for the concurrent review row lock'
                assert not expired_scoring.is_set(), 'Expired lease scored an uncommitted review as absent'
            finally:
                release_review.set()
                if event.contains(client.app.state.engine, 'before_cursor_execute', observe_attempt_read):
                    event.remove(client.app.state.engine, 'before_cursor_execute', observe_attempt_read)
            assert review_future.result(timeout=10).status_code == 200
            claim_response = claim_future.result(timeout=10)
            assert claim_response.status_code == 200 and claim_response.json()['job'] is None
        monkeypatch.setattr(banks, 'score_attempt', original_score)
    else:
        assert client.post(review_path, json=review_body).status_code == 200
        assert client.post('/internal/runner/claim', headers=headers, json={}).json()['job'] is None
    # Повтор зафиксированной review не должен вернуть устаревший aggregate.
    repeated = client.post(review_path, json=review_body).json()
    assert repeated['result']['tasks'][3]['score'] == 100
    login(client, 'candidate-a')
    final = client.get('/api/v1/candidate/bank-attempts/'+attempt['id']).json()
    assert final['result']['pending_count'] == 1 and final['result']['tasks'][4]['score'] is None
    assert final['result']['tasks'][3]['score'] == 100


def test_infrastructure_result_retry_and_candidate_recovery_preserves_frozen_source(client, monkeypatch):
    monkeypatch.setenv('FSP_RUNNER_TOKEN', 'synthetic-runner-token-for-tests')
    bank = create_bank(client, True); version = publish(client, bank); attempt = begin(client, bank, version)
    source = 'print(0)'
    saved = save(client, attempt, {'sum-python': source})
    client.post('/api/v1/candidate/bank-attempts/'+attempt['id']+'/submit', json={'revision': saved['revision']})
    headers = {'Authorization': 'Bearer synthetic-runner-token-for-tests'}
    first = client.post('/internal/runner/claim', headers=headers, json={}).json()['job']
    body = {'lease_token': first['lease_token'], 'status': 'system_error', 'passed': 0, 'total': 2, 'duration_ms': 500, 'runtime_version': 'test-vm', 'error_code': 'boot_failed'}
    path = '/internal/runner/jobs/'+first['id']+'/result'
    assert client.post(path, headers=headers, json=body).status_code == 200
    second = client.post('/internal/runner/claim', headers=headers, json={}).json()['job']
    assert second['id'] == first['id'] and second['lease_token'] != first['lease_token']
    body['lease_token'] = second['lease_token']
    assert client.post(path, headers=headers, json=body).status_code == 200
    assert client.get('/api/v1/candidate/bank-attempts/'+attempt['id']).json()['result']['tasks'][4]['score'] is None
    rerun = '/api/v1/candidate/bank-attempts/'+attempt['id']+'/code-jobs'
    assert client.post(rerun, json={'task_id': 'sum-python', 'source': 'print(14)'}).status_code == 409
    recovered = client.post(rerun, json={'task_id': 'sum-python', 'source': source})
    assert recovered.status_code == 201 and recovered.json()['id'] != first['id']


def test_job_budget_reserves_final_execution_and_blocks_oversized_code_set(client, monkeypatch):
    monkeypatch.setenv('FSP_RUNNER_TOKEN', 'synthetic-runner-token-for-tests')
    bank = create_bank(client, True); version = publish(client, bank); attempt = begin(client, bank, version)
    with client.app.state.factory() as db:
        for index in range(10):
            db.add(BankCodeJob(attempt_id=attempt['id'], task_id='sum-python', source='print('+str(index)+')',
                              source_hash=str(index)*64, status='completed'))
        db.commit()
    assert client.post('/api/v1/candidate/bank-attempts/'+attempt['id']+'/code-jobs',
                       json={'task_id': 'sum-python', 'source': 'print(14)'}).status_code == 429
    saved = save(client, attempt, {'sum-python': 'print(14)', 'sum-js': 'console.log(14)', 'count-sql': 'SELECT 14'})
    assert client.post('/api/v1/candidate/bank-attempts/'+attempt['id']+'/submit', json={'revision': saved['revision']}).status_code == 200
    with client.app.state.factory() as db:
        jobs = list(db.scalars(select(BankCodeJob).where(BankCodeJob.attempt_id == attempt['id'])))
        assert len(jobs) == 13 and sum(job.status == 'queued' for job in jobs) == 3
    login(client, 'employer-x')
    oversized = document(True); oversized.pop('schema_version'); oversized['external_id'] = 'oversized'
    prototype = deepcopy(oversized['tasks'][4]); oversized['tasks'] = []
    for index in range(11):
        task = deepcopy(prototype); task['id'] = 'code-'+str(index); oversized['tasks'].append(task)
    created = client.post('/api/v1/company/banks', json=oversized).json()
    version = created['current_version']
    assert client.post(f"/api/v1/company/banks/{created['id']}/versions/{version['id']}/publish", json={'revision': version['revision']}).status_code == 422


def test_utf8_and_serialized_broker_budgets_and_bounded_csv():
    with pytest.raises(ValidationError): CodeSubmit(task_id='sum-python', source='я'*18000)
    with pytest.raises(ValidationError): CodeCase(input='漢'*9000)
    with pytest.raises(ValidationError): CodeCase(setup='漢'*12000)
    task = document(True)['tasks'][4]
    task['starter_code'] = 'я'*18000
    with pytest.raises(ValidationError): Task.model_validate(task)
    task = document(True)['tasks'][4]
    task['hidden_tests'] = [{'input': '\x00'*15000, 'output': '0'} for _ in range(10)]
    with pytest.raises(ValidationError): Task.model_validate(task)
    with pytest.raises(ValueError): validate_answers(document(True), {'sum-python': 'я'*18000})
    raw = 'id,type,title,prompt,skills,numeric_answer\n'+''.join(f'n{i},numeric,Число,Ответ?,testing,0\n' for i in range(101))
    assert parse_import(raw.encode(), 'too-many.csv')[1]

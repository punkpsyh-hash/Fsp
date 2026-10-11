"""Контракт и независимые эталоны конкурсного синтетического банка."""
import json
import sqlite3
from pathlib import Path

from src.server.bank_schemas import BankDocument, publication_errors


BANK_PATH = Path(__file__).parents[1] / 'requirements' / 'examples' / 'bank-contest.json'


def load_document():
    return json.loads(BANK_PATH.read_text(encoding='utf-8'))


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def event_oracle(raw):
    rows = json.loads(raw)
    first_by_id = {}
    for row in rows:
        first_by_id.setdefault(row['event_id'], row)
    balances = {row['account']: 0 for row in first_by_id.values()}
    applied, rejected = [], []
    ordered = sorted(first_by_id.values(), key=lambda row: (
        row['occurred_at'], row['sequence'], row['event_id']))
    for row in ordered:
        account = row['account']
        next_balance = balances.get(account, 0) + row['delta']
        if next_balance < 0:
            rejected.append(row['event_id'])
            continue
        balances[account] = next_balance
        applied.append(row['event_id'])
    return compact({
        'balances': [[key, balances[key]] for key in sorted(balances)],
        'applied': applied,
        'rejected': rejected,
    }) + '\n'


def journal_oracle(raw):
    rows = json.loads(raw)
    latest = {}
    for index, row in enumerate(rows):
        previous = latest.get(row['operation_id'])
        rank = (row['revision'], row['updated_at'], index)
        if previous is None or rank > previous[0]:
            latest[row['operation_id']] = (rank, row)
    summary = {}
    aliases = {
        'ok': 'succeeded', 'success': 'succeeded', 'succeeded': 'succeeded',
        'error': 'failed', 'failed': 'failed', 'pending': 'pending',
    }
    for _, row in latest.values():
        status = aliases[row['status'].strip().lower()]
        customer = row['customer']
        record = summary.setdefault(customer, {
            'customer': customer,
            'succeeded_count': 0,
            'succeeded_cents': 0,
            'failed_count': 0,
            'pending_count': 0,
        })
        if status == 'succeeded':
            record['succeeded_count'] += 1
            record['succeeded_cents'] += row['amount_cents']
        elif status == 'failed':
            record['failed_count'] += 1
        else:
            record['pending_count'] += 1
    return compact([summary[key] for key in sorted(summary)]) + '\n'


SQL_ORACLE = """SELECT c.id,
       COUNT(o.id),
       SUM(CASE WHEN o.status='paid' THEN 1 ELSE 0 END),
       COALESCE(SUM(CASE WHEN o.status='paid' THEN o.amount_cents ELSE 0 END), 0)
FROM customers AS c
LEFT JOIN orders AS o ON o.customer_id=c.id
WHERE c.active=1
GROUP BY c.id
ORDER BY c.id"""


def sql_oracle(case):
    connection = sqlite3.connect(':memory:')
    try:
        connection.executescript(case['setup'])
        return [list(row) for row in connection.execute(SQL_ORACLE).fetchall()]
    finally:
        connection.close()


def test_contest_bank_matches_schema_and_publication_rules():
    raw = load_document()
    document = BankDocument.model_validate(raw).model_dump(mode='json')

    assert document['schema_version'] == 'fsp-bank-v1'
    assert document['external_id'] == 'contest-backend-middle-v1'
    assert document['scope'] == 'employer'
    assert document['specialization'] == 'backend'
    assert document['grade'] == 'middle'
    assert len(document['tasks']) == 6
    assert sum(task['expected_minutes'] for task in document['tasks']) == 88
    assert sum(task['weight'] for task in document['tasks']) == 100
    assert {task['type'] for task in document['tasks']} == {
        'code', 'single_choice', 'multiple_choice', 'open_response'}
    assert not publication_errors(document)

    code = [task for task in document['tasks'] if task['type'] == 'code']
    assert {task['language'] for task in code} == {'python', 'javascript', 'sql'}
    assert all(task['examples'] and len(task['hidden_tests']) >= 3 for task in code)
    assert document['tasks'][4]['partial_credit'] is False
    assert document['tasks'][4]['answer_key'] == [
        'search-projection', 'owner-bound-grant', 'revoke-future-reads']

    all_text = json.dumps(document, ensure_ascii=False)
    assert '@' not in all_text
    assert 'example.invalid' not in all_text


def test_code_case_outputs_match_independent_spec_oracles():
    document = BankDocument.model_validate(load_document()).model_dump(mode='json')
    tasks = {task['id']: task for task in document['tasks']}
    for case in tasks['event-ledger']['examples'] + tasks['event-ledger']['hidden_tests']:
        assert case['output'] == event_oracle(case['input'])
    for case in tasks['journal-summary']['examples'] + tasks['journal-summary']['hidden_tests']:
        assert case['output'] == journal_oracle(case['input'])
    for case in tasks['customer-order-stats']['examples'] + tasks['customer-order-stats']['hidden_tests']:
        assert json.loads(case['output']) == sql_oracle(case)

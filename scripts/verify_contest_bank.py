"""Проверяет эталоны и типовые ошибки конкурсного банка только внутри VM."""
import argparse
import hashlib
import json
from pathlib import Path

from runner.engine import VMRunner


REFERENCE_SOLUTIONS = {
    'event-ledger': '''import json, sys
events = json.loads(sys.stdin.read())
first = {}
for event in events:
    first.setdefault(event['event_id'], event)
balances = {event['account']: 0 for event in first.values()}
applied, rejected = [], []
ordered = sorted(first.values(), key=lambda event: (
    event['occurred_at'], event['sequence'], event['event_id']))
for event in ordered:
    balance = balances[event['account']] + event['delta']
    if balance < 0:
        rejected.append(event['event_id'])
    else:
        balances[event['account']] = balance
        applied.append(event['event_id'])
result = {
    'balances': [[account, balances[account]] for account in sorted(balances)],
    'applied': applied,
    'rejected': rejected,
}
print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
''',
    'journal-summary': '''const fs = require('node:fs');
const rows = JSON.parse(fs.readFileSync(0, 'utf8'));
const latest = new Map();
rows.forEach((row, index) => {
  const previous = latest.get(row.operation_id);
  const newer = !previous || row.revision > previous.row.revision ||
    (row.revision === previous.row.revision && row.updated_at > previous.row.updated_at) ||
    (row.revision === previous.row.revision && row.updated_at === previous.row.updated_at && index > previous.index);
  if (newer) latest.set(row.operation_id, {row, index});
});
const aliases = {ok: 'succeeded', success: 'succeeded', succeeded: 'succeeded',
  error: 'failed', failed: 'failed', pending: 'pending'};
const summary = new Map();
for (const {row} of latest.values()) {
  const status = aliases[row.status.trim().toLowerCase()];
  if (!summary.has(row.customer)) summary.set(row.customer, {
    customer: row.customer, succeeded_count: 0, succeeded_cents: 0,
    failed_count: 0, pending_count: 0,
  });
  const item = summary.get(row.customer);
  if (status === 'succeeded') {
    item.succeeded_count += 1;
    item.succeeded_cents += row.amount_cents;
  } else if (status === 'failed') item.failed_count += 1;
  else item.pending_count += 1;
}
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
console.log(JSON.stringify([...summary.values()].sort((a, b) => compare(a.customer, b.customer))));
''',
    'customer-order-stats': '''SELECT c.id,
       COUNT(o.id),
       SUM(CASE WHEN o.status='paid' THEN 1 ELSE 0 END),
       COALESCE(SUM(CASE WHEN o.status='paid' THEN o.amount_cents ELSE 0 END), 0)
FROM customers AS c
LEFT JOIN orders AS o ON o.customer_id=c.id
WHERE c.active=1
GROUP BY c.id
ORDER BY c.id''',
}


TYPICAL_MUTANTS = {
    # Ошибка: повторная доставка события применяется повторно.
    'event-ledger': '''import json, sys
events = json.loads(sys.stdin.read())
balances = {event['account']: 0 for event in events}
applied, rejected = [], []
for event in sorted(events, key=lambda row: (row['occurred_at'], row['sequence'], row['event_id'])):
    balance = balances[event['account']] + event['delta']
    if balance < 0: rejected.append(event['event_id'])
    else:
        balances[event['account']] = balance
        applied.append(event['event_id'])
print(json.dumps({'balances': [[key, balances[key]] for key in sorted(balances)],
                  'applied': applied, 'rejected': rejected}, separators=(',', ':')))
''',
    # Ошибка: агрегируется вся история, а не последняя ревизия операции.
    'journal-summary': '''const fs = require('node:fs');
const rows = JSON.parse(fs.readFileSync(0, 'utf8'));
const aliases = {ok: 'succeeded', success: 'succeeded', succeeded: 'succeeded',
  error: 'failed', failed: 'failed', pending: 'pending'};
const summary = new Map();
for (const row of rows) {
  const status = aliases[row.status.trim().toLowerCase()];
  if (!summary.has(row.customer)) summary.set(row.customer, {
    customer: row.customer, succeeded_count: 0, succeeded_cents: 0,
    failed_count: 0, pending_count: 0,
  });
  const item = summary.get(row.customer);
  if (status === 'succeeded') { item.succeeded_count += 1; item.succeeded_cents += row.amount_cents; }
  else if (status === 'failed') item.failed_count += 1;
  else item.pending_count += 1;
}
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
console.log(JSON.stringify([...summary.values()].sort((a, b) => compare(a.customer, b.customer))));
''',
    # Ошибка: INNER JOIN удаляет активных клиентов без заказов.
    'customer-order-stats': '''SELECT c.id,
       COUNT(o.id),
       SUM(CASE WHEN o.status='paid' THEN 1 ELSE 0 END),
       COALESCE(SUM(CASE WHEN o.status='paid' THEN o.amount_cents ELSE 0 END), 0)
FROM customers AS c
JOIN orders AS o ON o.customer_id=c.id
WHERE c.active=1
GROUP BY c.id
ORDER BY c.id''',
}


def runner_cases(task, cases=None):
    selected = task['examples'] + task['hidden_tests'] if cases is None else cases
    return [
        {
            'stdin': case['input'],
            'setup': case['setup'],
            'expected': json.loads(case['output']) if task['language'] == 'sql' else case['output'],
        }
        for case in selected
    ]


def grade(runner, task, source, cases):
    return runner.grade({
        'id': 'contest-bank-validation',
        'lease_token': 'contest-bank-validation-token',
        'language': task['language'],
        'source': source,
        'time_limit_seconds': task['runtime_limits']['wall_seconds'],
        'tests': cases,
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bank', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    bank_path = Path(args.bank)
    bank_bytes = bank_path.read_bytes()
    document = json.loads(bank_bytes)
    tasks = {task['id']: task for task in document['tasks']}
    if set(REFERENCE_SOLUTIONS) != set(TYPICAL_MUTANTS):
        raise AssertionError('reference/mutant task sets differ')
    runner = VMRunner()
    checks = {}

    for task_id, source in REFERENCE_SOLUTIONS.items():
        task = tasks[task_id]
        result = grade(runner, task, source, runner_cases(task))
        passed = result['status'] == 'passed' and result['passed'] == result['total']
        checks['reference:' + task_id] = {
            'status': 'passed' if passed else result['status'],
            'cases_passed': result['passed'],
            'cases_total': result['total'],
        }
        if not passed:
            raise AssertionError('reference solution failed: ' + task_id)

    for task_id, source in TYPICAL_MUTANTS.items():
        task = tasks[task_id]
        visible = grade(runner, task, source, runner_cases(task, task['examples']))
        hidden = grade(runner, task, source, runner_cases(task, task['hidden_tests']))
        killed = (visible['status'] == 'passed' and visible['passed'] == visible['total']
                  and hidden['status'] == 'wrong_answer')
        checks['mutant:' + task_id] = {
            'public_examples': visible['status'],
            'hidden_cases': hidden['status'],
            'hidden_cases_passed': hidden['passed'],
            'hidden_cases_total': hidden['total'],
            'killed_by_hidden_cases': killed,
        }
        if not killed:
            raise AssertionError('typical mutant survived: ' + task_id)

    report = {
        'kind': 'contest_bank_vm_reference_and_mutant_check',
        'bank_external_id': document['external_id'],
        'bank_sha256': hashlib.sha256(bank_bytes).hexdigest(),
        'accelerator': runner.accelerator,
        'versions': runner.versions,
        'checks': checks,
        'summary': {
            'reference_solutions_passed': len(REFERENCE_SOLUTIONS),
            'typical_mutants_killed': sum(
                check['killed_by_hidden_cases'] for key, check in checks.items()
                if key.startswith('mutant:')),
        },
        'limitations': [
            'Только программные эталоны и три заранее заданных типовых ошибки.',
            'Это не экспертная калибровка, human pilot или подтверждение уровня Backend Middle.',
        ],
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

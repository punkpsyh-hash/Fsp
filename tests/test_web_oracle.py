"""Cross-check the test-only JavaScript oracle against private saved answers.

The JavaScript child receives only the fields exposed by public_question_form.
Run this test where Node 22 is available; the backend-only image skips it, while
the release check executes it in the pinned Node container.
"""
import json
from functools import lru_cache
import hashlib
from pathlib import Path
import shutil
import subprocess

import pytest

from src.server.assessment import public_question_form, questions


ROOT = Path(__file__).parents[1]
NODE = shutil.which('node')


@lru_cache(maxsize=1)
def oracle_matrix():
    cases = []
    for version in ('scenarios-v5', 'scenarios-v6'):
        for grade in ('junior', 'middle'):
            for seed in range(100):
                private = questions(seed, grade, 'backend', version)
                public = public_question_form(private)
                assert all(set(row) == {'id', 'skill', 'title', 'options'} for row in public)
                cases.extend({
                    'question': {**issued, 'id': hashlib.sha256(
                        f'{version}:{grade}:{seed}:{index}'.encode()).hexdigest()[:24]},
                    'grade': grade,
                    'expected': saved['answer'],
                    'version': version,
                    'family': saved['family'],
                } for index, (saved, issued) in enumerate(zip(private, public)))
    return cases


def test_backend_matrix_exposes_only_public_inputs():
    cases = oracle_matrix()
    assert len(cases) == 4800
    assert {case['family'] for case in cases} == {
        'py-selection', 'py-default', 'py-copy', 'py-errors',
        'sql-null-data', 'sql-aggregate-data', 'sql-left-data', 'sql-order-data',
        'http-idempotency-trace', 'http-contact-revoke',
        'http-conditional-write', 'http-object-scope',
    }
    assert all(len(case['question']['id']) == 24
               and set(case['question']['id']) <= set('0123456789abcdef')
               and case['question']['id'] != case['family'] for case in cases)


def test_javascript_oracle_has_no_private_or_dynamic_execution_path():
    source = (ROOT / 'web/scripts/scenario-oracle.mjs').read_text(encoding='utf-8')
    assert '.parameters' not in source and '.family' not in source
    assert 'eval(' not in source and 'new Function' not in source
    assert not any(family in source for family in {
        'py-selection', 'py-default', 'py-copy', 'py-errors',
        'sql-null-data', 'sql-aggregate-data', 'sql-left-data', 'sql-order-data',
        'http-idempotency-trace', 'http-contact-revoke',
        'http-conditional-write', 'http-object-scope',
    })


def test_public_title_oracle_matches_all_backend_families():
    if NODE is None:
        pytest.skip('Node is absent; release check runs this test in node:22-bookworm-slim')
    cases = oracle_matrix()
    script = """
import { scenarioAnswer } from './web/scripts/scenario-oracle.mjs';
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const cases = JSON.parse(Buffer.concat(chunks).toString('utf8'));
const failures = cases.flatMap((item, index) => {
  const actual = scenarioAnswer(item.question, item.grade);
  return actual === item.expected ? [] : [{index, actual, ...item}];
});
if (failures.length) {
  console.error(JSON.stringify(failures.slice(0, 5), null, 2));
  process.exit(1);
}
console.log(JSON.stringify({cases: cases.length}));
"""
    completed = subprocess.run(
        [NODE, '--input-type=module', '--eval', script],
        cwd=ROOT,
        input=json.dumps(cases, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {'cases': 4800}

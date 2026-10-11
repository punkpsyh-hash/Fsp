"""Проверка локального контракта и безопасных HTTP-примеров без их отправки."""
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.request
import argparse

from jsonschema import Draft202012Validator
import yaml

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=root / 'docs/release/current-documents/api-contract.json',
                    help='Куда записать текущий JSON-отчёт; исторические протоколы не перезаписываются.')
args = parser.parse_args()
schema = yaml.safe_load((root / 'contracts/openapi.yaml').read_text())
guide = (root / 'docs/18-api-guide.md').read_text()
operations = {(method.upper(), path) for path, methods in schema['paths'].items()
              for method in methods if method in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options'}}
documented = set(re.findall(r'^\| (GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) \| `([^`]+)` \|', guide, re.M))
assert documented == operations, {'missing': sorted(operations - documented), 'extra': sorted(documented - operations)}
runtime = json.load(urllib.request.urlopen(os.environ.get('FSP_VERIFY_API_URL', 'http://127.0.0.1:8470')+'/api/openapi.json', timeout=10))
assert runtime == schema, 'Live OpenAPI differs from committed contract'

source = (root / 'docs/api-examples.http').read_text()
examples = bodies = 0
for block in source.split('###')[1:]:
    request = re.search(r'^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) \{\{base\}\}([^\n]+)', block, re.M)
    assert request, 'Example has no request'
    method, path = request.groups()
    path = path.split('?')[0]
    path = re.sub(r'\{\{[^}]+\}\}', 'example-id', path)
    matches = [(method, path)] if (method, path) in operations else [key for key in operations if key[0] == method and re.fullmatch(re.sub(r'\{[^}]+\}', '[^/]+', key[1]), path)]
    assert len(matches) == 1, (method, path, matches)
    examples += 1
    if 'Content-Type: application/json' not in block:
        continue
    body = block.split('Content-Type: application/json', 1)[1].strip()
    body = '\n'.join(line for line in body.splitlines() if not line.startswith(('Cookie:', 'X-CSRF-Token:', 'Authorization:', '#'))).strip()
    body = re.sub(r'"\{\{([^}]+)\}\}"', lambda m: json.dumps('passed' if m[1] == 'execution_status' else 'safe-placeholder-value'), body)
    body = re.sub(r'\{\{[^}]+\}\}', '1', body)
    value = json.loads(body)
    operation = schema['paths'][matches[0][1]][method.lower()]
    request_schema = operation['requestBody']['content']['application/json']['schema']
    Draft202012Validator({**request_schema, 'components': schema['components']}).validate(value)
    bodies += 1
result = {'paths': len(schema['paths']), 'operations': len(operations),
          'documented_operations': len(documented), 'live_contract_equal': True,
          'http_examples': examples, 'json_bodies_validated': bodies,
          'http_examples_executed_as_requests': False,
          'method': 'Offline route/body validation with safe placeholder substitution; only public GET OpenAPI is requested.',
          'source_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in
                            ('contracts/openapi.yaml', 'docs/18-api-guide.md', 'docs/api-examples.http')}}
output = args.output if args.output.is_absolute() else root / args.output
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result))

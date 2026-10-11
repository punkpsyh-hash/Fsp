"""Пересчёт автопроверки по сохранённым сырым ответам (без вызова модели)."""
import json
import sys
from pathlib import Path

from src.server import bank_generation as bg
from ml.eval_adapter import auto_check

result, checks_path = Path(sys.argv[1]), Path(sys.argv[2])
data = json.loads(result.read_text(encoding='utf-8'))
checks = json.loads(checks_path.read_text(encoding='utf-8'))['checks']
passed = total = 0
for row in data['rows']:
    if not row['structural'] or row['id'] not in checks:
        continue
    task = bg._prepare_raw(json.loads(row['raw']))
    ok, note = auto_check(task, checks[row['id']])
    total += 1
    passed += bool(ok)
    print(row['id'], ok, note[:70])
print('auto', passed, '/', total)

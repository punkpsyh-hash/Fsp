"""Tiny regression fixture, NOT a market or psychometric quality estimate."""
import json
import sys
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.domain import Candidate, Need, rank

need = Need("backend", "junior", frozenset({"python"}), frozenset({"sql"}), 150000)
data = [
    Candidate("c01", "backend", "junior", frozenset({"python", "sql"}), 94, 0, 1, True, salary_min=100000),
    Candidate("c02", "backend", "junior", frozenset({"python", "sql"}), 80, .8, .7, True, salary_min=120000),
    Candidate("c03", "backend", "junior", frozenset({"python"}), 95, 1, 1, True, salary_min=90000),
    Candidate("c04", "frontend", "junior", frozenset({"python", "sql"}), 99, 1, 1, True),
    Candidate("c05", "backend", None, frozenset({"python", "sql"}), 100, 1, 1, True),
    Candidate("c06", "backend", "junior", frozenset({"python", "sql"}), 90, 1, 1, False),
]
rows = rank(data, need)
expected = ["c01", "c02", "c03"]
assert [r["id"] for r in rows] == expected, rows
result = {"type": "synthetic_regression_fixture", "query_count": 1, "candidate_count": len(data),
          "expected_order": expected, "actual_order": [r["id"] for r in rows], "passed": True,
          "python": platform.python_version(), "rows": rows,
          "limitation": "Hand-authored fixture; not independent expert validation, precision estimate or evidence of hiring outcomes."}
(ROOT / "docs/results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(result, ensure_ascii=False, indent=2))

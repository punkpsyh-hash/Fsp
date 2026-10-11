"""Контракт только реально реализованных операций, без внешних API ФСП."""
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.server.app import create_app

schema = create_app("sqlite://", demo=True, seed=False).openapi()
(ROOT/"contracts"/"openapi.yaml").write_text(yaml.safe_dump(schema, allow_unicode=True, sort_keys=False))
print("Контракт экспортирован; путей:", len(schema["paths"]))

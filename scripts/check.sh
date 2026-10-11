#!/bin/sh
# Выполняется в tools-контейнере, без удаления рабочей базы.
set -eu
python -m pytest tests -q -p no:cacheprovider
FSP_TEST_POSTGRES=1 python -m pytest tests -q -p no:cacheprovider
python -m alembic check
python scripts/evaluate.py
python -m scripts.benchmark
python scripts/review_assessment_variants.py
python scripts/verify_assessment_current.py
python scripts/export_contract.py

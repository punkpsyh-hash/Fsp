#!/bin/sh
# Миграции завершаются до запуска API; exec обеспечивает штатную остановку.
set -eu
FSP_FORWARDED_ALLOW_IPS="${FSP_FORWARDED_ALLOW_IPS:-127.0.0.1}"
python -m alembic upgrade head
exec python -m uvicorn src.server.app:app --host 0.0.0.0 --port 8470 --no-access-log \
  --proxy-headers --forwarded-allow-ips "$FSP_FORWARDED_ALLOW_IPS"

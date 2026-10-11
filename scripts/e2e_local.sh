#!/bin/bash
# Браузерные сценарии без Compose: SQLite-стенд и Playwright в изолированной Docker-сети.
#   scripts/e2e_local.sh [аргументы playwright, например e2e/a11y.spec.ts --project=chromium]
# Образы проекта пересобираются из текущих файлов; внешнее окружение Python не требуется.
set -euo pipefail
cd "$(dirname "$0")/.."
P="$(pwd -W 2>/dev/null || pwd)"
NET="fsp-e2e-net-$$"; APP="fsp-e2e-app-$$"
API_IMAGE="${API_IMAGE:-fsp-app:latest}"
BROWSER_IMAGE="${BROWSER_IMAGE:-fsp-browser:latest}"
PY="${PY:-/opt/venv/bin/python}"
export MSYS_NO_PATHCONV=1
docker build --target runtime -t "$API_IMAGE" .
docker build -f docker/browser.Dockerfile -t "$BROWSER_IMAGE" .
docker run --rm -v "$P/web:/w" -w /w node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 sh -c "npm ci --ignore-scripts --no-fund --no-audit && npm run build"
docker network create --internal "$NET" >/dev/null
cleanup() {
  docker rm -f "$APP" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker run -d --name "$APP" --network "$NET" --network-alias stand --pull never \
  --mount "type=bind,source=$P,target=/workspace/Fsp,readonly" \
  --read-only --tmpfs /tmp:rw,nosuid,nodev,size=128m --cap-drop ALL --security-opt no-new-privileges:true \
  -w /workspace/Fsp -e PYTHONPATH=/workspace/Fsp -e PYTHONDONTWRITEBYTECODE=1 \
  -e FSP_ALLOWED_HOSTS=stand -e FSP_ALLOWED_ORIGINS=http://stand:8470 -e FSP_AUTH_RATE_LIMIT=500 -e FSP_SQLITE_POOL=1 -e FSP_INTEGRITY_ENFORCE=0 --entrypoint "$PY" "$API_IMAGE" \
  scripts/dev_local.py --host 0.0.0.0 --port 8470 --db /tmp/e2e.sqlite >/dev/null
ready=0
for _ in $(seq 1 30); do
  if docker exec "$APP" "$PY" -c "import urllib.request as u;u.urlopen('http://127.0.0.1:8470/api/health',timeout=2)" >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 2
done
[[ "$ready" == 1 ]] || { printf 'Тестовый API не стал готов за отведённое время.\n' >&2; exit 1; }
rc=0
docker run --rm --network "$NET" --pull never -e FSP_TEST_URL=http://stand:8470 -e FSP_TEST_OUTPUT=/tmp/results \
  --mount "type=bind,source=$P/web/e2e,target=/app/web/e2e,readonly" "$BROWSER_IMAGE" \
  npx playwright test "${@:---project=chromium}" || rc=$?
exit $rc

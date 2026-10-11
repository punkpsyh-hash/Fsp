#!/usr/bin/env bash
# Полный цикл через Docker; локальные Python/Node не нужны, секреты не выводятся.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export FSP_UID="$(id -u)" FSP_GID="$(id -g)"
workspace_mount="$PWD"
if command -v cygpath >/dev/null 2>&1; then
  workspace_mount="$(cygpath -m "$PWD")"
  export MSYS_NO_PATHCONV=1 COMPOSE_PATH_SEPARATOR="${COMPOSE_PATH_SEPARATOR:-:}"
fi
case "${1:-start}" in
  start-llm|stop-llm|status-llm|check-llm|model-report)
    compose_separator="${COMPOSE_PATH_SEPARATOR:-:}"
    export COMPOSE_FILE="${COMPOSE_FILE:-compose.yaml}"
    if [[ "${compose_separator}${COMPOSE_FILE}${compose_separator}" != *"${compose_separator}compose.llm.yaml${compose_separator}"* ]]; then
      export COMPOSE_FILE="${COMPOSE_FILE}${compose_separator}compose.llm.yaml"
    fi
    ;;
esac
if [[ -c /dev/kvm && "${FSP_RUNNER_ACCEL:-kvm}" != tcg ]]; then
  export FSP_KVM_GID="$(stat -c '%g' /dev/kvm)" FSP_RUNNER_ACCEL=kvm
else
  export FSP_RUNNER_ACCEL=tcg
  compose_separator="${COMPOSE_PATH_SEPARATOR:-:}"
  if [[ -z "${COMPOSE_FILE:-}" ]]; then
    export COMPOSE_FILE="compose.yaml${compose_separator}compose.runner-tcg.yaml"
  elif [[ "${compose_separator}${COMPOSE_FILE}${compose_separator}" != *"${compose_separator}compose.runner-tcg.yaml${compose_separator}"* ]]; then
    export COMPOSE_FILE="${COMPOSE_FILE}${compose_separator}compose.runner-tcg.yaml"
  fi
fi
init_env() {
  docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges:true \
    --user "$FSP_UID:$FSP_GID" --workdir /workspace \
    --mount "type=bind,src=$workspace_mount,dst=/workspace" \
    python:3.12-slim@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e \
    python scripts/init_env.py
}
start_app() {
  init_env
  docker compose up -d --build --wait --wait-timeout "${FSP_START_WAIT_TIMEOUT:-900}" app runner
}
model_files() {
  local model_network=bridge
  [[ "${1:-}" != --verify-only ]] || model_network=none
  docker run --rm --network "$model_network" --cap-drop ALL --security-opt no-new-privileges:true \
    --user "$FSP_UID:$FSP_GID" --workdir /workspace \
    --mount "type=bind,src=$workspace_mount,dst=/workspace" \
    python:3.12-slim@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e \
    python ml/fetch_model.py "$@"
}
tools_run() {
  start_app
  docker compose build tools
  docker compose run --rm -T --no-deps tools "$@"
}
browser_run() {
  start_app
  mkdir -p web/test-results docs/delivery
  docker compose build browser
  docker compose run --rm -T --no-deps browser "$@"
}
contest_bank() {
  docker compose run --rm -T --no-deps --user "$FSP_UID:$FSP_GID" \
    --volume "$workspace_mount/scripts/verify_contest_bank.py:/app/verify_contest_bank.py:ro" \
    --volume "$workspace_mount/requirements/examples/bank-contest.json:/bank.json:ro" \
    --volume "$workspace_mount/docs:/evidence" runner python /app/verify_contest_bank.py \
    --bank /bank.json --output /evidence/contest-bank-results.json
}
case "${1:-start}" in
  init) init_env ;;
  model-fetch) model_files ;;
  model-verify) model_files --verify-only ;;
  start-llm)
    model_files --verify-only
    start_app
    printf 'Стенд с локальной моделью: http://127.0.0.1:8470 (или порт выбранного overlay).\n'
    ;;
  start)
    start_app
    if [[ "${COMPOSE_FILE:-}" == *compose.verify.yaml* || "${COMPOSE_FILE:-}" == *compose.isolated.yaml* ]]; then
      printf 'Изолированный стенд запущен без публикации портов.\n'
    elif [[ "${COMPOSE_FILE:-}" == *compose.delivery.yaml* ]]; then
      printf 'Отдельный конкурсный стенд: http://127.0.0.1:8471\n'
    else
      printf 'Конкурсный стенд: http://127.0.0.1:8470\n'
    fi
    ;;
  build) init_env; docker compose build app runner ;;
  status|status-llm) docker compose ps ;;
  check|check-llm)
    docker compose ps
    check_args=()
    [[ "${1:-}" != check-llm ]] || check_args+=(--require-local-llm)
    docker compose exec -T app python - "${check_args[@]}" < scripts/check_stand.py
    ;;
  model-report)
    docker compose run --rm -T --no-deps model python -c "from pathlib import Path; print(Path('/diagnostics/startup.json').read_text())"
    ;;
  stop|stop-llm) docker compose stop ;;
  logs) docker compose logs --tail 100 app runner ;;
  test) tools_run python -m pytest tests -q -p no:cacheprovider ;;
  test-postgres) tools_run env FSP_TEST_POSTGRES=1 python -m pytest tests -q -p no:cacheprovider ;;
  ranking) tools_run python scripts/evaluate.py ;;
  contract) tools_run python scripts/export_contract.py ;;
  api-check) tools_run python scripts/verify_api_guide.py ;;
  pilot-review) tools_run python scripts/analyze_pilot.py --input requirements/pilot/observations.csv --output docs/pilot-readiness.json ;;
  report)
    document_user="$FSP_UID:$FSP_GID"
    if command -v cygpath >/dev/null 2>&1; then
      document_user=0:0
    fi
    docker build --target tools -t fsp-documents .
    docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges:true \
      --user "$document_user" --workdir /app \
      --mount "type=bind,src=$workspace_mount,dst=/app" \
      fsp-documents python scripts/build_gost_bundle.py
    ;;
  load) tools_run python scripts/validate_load.py ;;
  load-workflow) tools_run python -m scripts.validate_workflow_load ;;
  benchmark) tools_run python -m scripts.benchmark ;;
  assessment-review) tools_run python scripts/review_assessment_variants.py ;;
  assessment-current) tools_run python scripts/verify_assessment_current.py ;;
  runner-test)
    start_app
    docker compose run --rm -T --no-deps --volume "$workspace_mount/docs:/evidence" --user "$FSP_UID:$FSP_GID" runner python -m runner.probe --output /evidence/runner-results.json
    ;;
  contest-bank) start_app; contest_bank ;;
  e2e) browser_run npm run test:e2e ;;
  demo) browser_run npm run demo:record ;;
  demo-check)
    start_app
    docker compose build browser
    app_container_id="$(docker compose ps -q app)"
    [[ -n "$app_container_id" ]] || { printf 'Контейнер app не найден.\n' >&2; exit 1; }
    FSP_DEPLOYMENT_IMAGE="$(docker inspect "$app_container_id" --format '{{.Image}}')" \
      docker compose run --rm -T --no-deps -e FSP_DEPLOYMENT_IMAGE \
      --volume "$workspace_mount/docs:/app/docs" browser node scripts/verify-media.mjs
    ;;
  verify)
    tools_run sh scripts/check.sh
    docker compose run --rm -T --no-deps runner python -m runner.probe --smoke
    contest_bank
    browser_run npm run test:e2e
    ;;
  backup)
    init_env
    mkdir -p backups
    backup_file="$(mktemp "backups/fsp-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX.dump")"
    # Проверки создают/удаляют отдельные схемы; они не являются рабочими данными.
    if ! docker compose exec -T db pg_dump -U fsp -d fsp --format=custom --exclude-schema='fsp_test_*' > "$backup_file"; then
      rm -- "$backup_file"
      exit 1
    fi
    printf 'Резервная копия: %s\n' "$backup_file"
    ;;
  package) bash scripts/package_submission.sh ;;
  *)
    printf 'Использование: %s {init|start|start-llm|stop-llm|status-llm|check-llm|model-fetch|model-verify|model-report|check|build|status|stop|logs|test|test-postgres|ranking|contract|api-check|pilot-review|report|load|load-workflow|benchmark|assessment-review|assessment-current|runner-test|contest-bank|e2e|demo|demo-check|verify|backup|package}\n' "$0" >&2
    exit 2
    ;;
esac

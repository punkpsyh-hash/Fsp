#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
docker build -f docker/runner.Dockerfile -t fsp-runner .
MODE="${1:-kvm}"
case "$MODE" in kvm|tcg) ;; *) echo 'Использование: ./scripts/runner-probe.sh [kvm|tcg]' >&2; exit 2 ;; esac
# A single new output file is mounted; no project source/material directory is shared.
REPORT_TMP="$(mktemp "$PROJECT_DIR/docs/.runner-probe-$MODE-XXXXXX.json")"
trap 'rm -f -- "$REPORT_TMP"' EXIT
case "$MODE" in
  kvm)
    test -c /dev/kvm || { echo 'KVM отсутствует. Используйте явный режим tcg.' >&2; exit 1; }
    docker run --rm --network none --read-only --cap-drop ALL \
      --security-opt no-new-privileges --device /dev/kvm \
      --group-add "$(stat -c '%g' /dev/kvm)" --memory 1g --cpus 1 --pids-limit 64 \
      --tmpfs /tmp:size=1g,mode=1777 --user "$(id -u):$(id -g)" \
      --volume "$REPORT_TMP:/probe-result.json" \
      fsp-runner python -m runner.probe --output /probe-result.json
    ;;
  tcg)
    docker run --rm --network none --read-only --cap-drop ALL \
      --security-opt no-new-privileges --memory 1g --cpus 1 --pids-limit 64 \
      --tmpfs /tmp:size=1g,mode=1777 --env FSP_RUNNER_ACCEL=tcg \
      --user "$(id -u):$(id -g)" --volume "$REPORT_TMP:/probe-result.json" \
      fsp-runner python -m runner.probe --smoke --output /probe-result.json
    ;;
  *) echo 'Использование: ./scripts/runner-probe.sh [kvm|tcg]' >&2; exit 2 ;;
esac
mv -- "$REPORT_TMP" "$PROJECT_DIR/docs/runner-results-$MODE.json"

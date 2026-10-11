"""Регрессии Compose и обёрток запуска без обращения к Docker daemon."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ENV = {
    "FSP_DEMO_LOGIN": "${FSP_DEMO_LOGIN:-1}",
    "FSP_MOCK_MAIL": "${FSP_MOCK_MAIL:-1}",
    "FSP_ALLOWED_HOSTS": "${FSP_ALLOWED_HOSTS:-}",
    "FSP_ALLOWED_ORIGINS": "${FSP_ALLOWED_ORIGINS:-}",
    "FSP_COOKIE_SECURE": "${FSP_COOKIE_SECURE:-0}",
    "FSP_INTEGRITY_ENFORCE": "${FSP_INTEGRITY_ENFORCE:-1}",
    "FSP_CONFIRMATION_BAND": "${FSP_CONFIRMATION_BAND:-6}",
    "FSP_REGISTRY_UNAVAILABLE": "${FSP_REGISTRY_UNAVAILABLE:-0}",
    "FSP_LLM_PROVIDER": "${FSP_LLM_PROVIDER:-none}",
    "FSP_LLM_BASE_URL": "${FSP_LLM_BASE_URL:-}",
    "FSP_LLM_MODEL": "${FSP_LLM_MODEL:-}",
    "FSP_LLM_API_KEY": "${FSP_LLM_API_KEY:-}",
    "FSP_LLM_TIMEOUT": "${FSP_LLM_TIMEOUT:-8}",
}


def test_compose_forwards_runtime_configuration_only_to_app():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    app_env = services["app"]["environment"]
    tools_env = services["tools"]["environment"]

    assert {key: app_env.get(key) for key in RUNTIME_ENV} == RUNTIME_ENV
    assert RUNTIME_ENV.keys().isdisjoint(tools_env)


@pytest.mark.skipif(shutil.which("bash") is None, reason="run.sh проверяется в Linux tools-образе")
@pytest.mark.parametrize(
    ("initial", "expected"),
    [
        ("compose.yaml:compose.isolated.yaml", "compose.yaml:compose.isolated.yaml:compose.runner-tcg.yaml"),
        ("compose.yaml:compose.runner-tcg.yaml:compose.isolated.yaml", "compose.yaml:compose.runner-tcg.yaml:compose.isolated.yaml"),
        (None, "compose.yaml:compose.runner-tcg.yaml"),
    ],
)
def test_run_sh_preserves_compose_overlays_when_tcg_is_required(tmp_path, initial, expected):
    capture = tmp_path / "compose-file.txt"

    env = os.environ.copy()
    env.update({
        "CAPTURE_FILE": str(capture),
        "FSP_RUNNER_ACCEL": "tcg",
    })
    if initial is None:
        env.pop("COMPOSE_FILE", None)
    else:
        env["COMPOSE_FILE"] = initial

    # /tmp tools-контейнера намеренно noexec; shell-функция сохраняет эту границу.
    stub = 'docker() { printf "%s" "${COMPOSE_FILE-}" > "$CAPTURE_FILE"; }; export -f docker; bash scripts/run.sh status'
    subprocess.run(["bash", "-c", stub], cwd=ROOT, env=env, check=True)
    assert capture.read_text(encoding="utf-8") == expected


def test_one_off_checks_do_not_restart_dependencies_and_demo_check_resolves_app():
    script = (ROOT / "scripts/run.sh").read_text(encoding="utf-8")

    assert 'docker compose run --rm -T --no-deps tools "$@"' in script
    assert 'docker compose run --rm -T --no-deps browser "$@"' in script
    assert 'docker compose run --rm -T --no-deps --volume "$workspace_mount/docs:/evidence"' in script
    assert 'docker compose ps -q app' in script
    assert "fsp-app-1" not in script

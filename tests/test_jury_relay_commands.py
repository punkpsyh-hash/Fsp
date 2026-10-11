"""Проверка реальной команды relay без Docker daemon, ключей и сетевых вызовов."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def command_fixture(tmp_path, mode):
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    script = project / "scripts/jury-relay-nas.sh"
    shutil.copyfile(ROOT / "scripts/jury-relay-nas.sh", script)
    key, hosts = project / "dummy-key", project / "dummy-hosts"
    key.write_text("test fixture only", encoding="utf-8")
    hosts.write_text("test fixture only", encoding="utf-8")
    entries = {
        "FSP_JURY_DOMAIN": "fsptest.kolesnikovny.ru",
        "FSP_JURY_VPS_HOST": "80.87.198.60",
        "FSP_JURY_VPS_SSH_PORT": "22",
        "FSP_JURY_TUNNEL_USER": "fspjury-tunnel",
        "FSP_JURY_SSH_KEY_PATH": str(key),
        "FSP_JURY_SSH_KNOWN_HOSTS_PATH": str(hosts),
        "FSP_JURY_INDIVIDUAL_REGISTRATION": mode,
    }
    (project / ".env.jury").write_text("".join(f"{k}='{v}'\n" for k, v in entries.items()), encoding="utf-8")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    docker = binaries / "docker"
    docker.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$JURY_COMMAND_RECORD"\nprintf "END\\n" >> "$JURY_COMMAND_RECORD"\n', encoding="utf-8")
    docker.chmod(0o755)
    stat = binaries / "stat"
    stat.write_text('#!/bin/sh\ncase "$2" in %u) echo 10001;; %a) echo 600;; *) exit 1;; esac\n', encoding="utf-8")
    stat.chmod(0o755)
    record = tmp_path / "commands.txt"
    env = {**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
           "JURY_COMMAND_RECORD": str(record)}
    return script, record, env


@pytest.mark.parametrize("mode,expected", [("0", 3), ("", 3), ("1", 5)])
def test_status_uses_the_selected_closed_or_individual_compose_chain(tmp_path, mode, expected):
    script, record, env = command_fixture(tmp_path, mode)
    result = subprocess.run(["bash", str(script), "status"], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    args = record.read_text(encoding="utf-8").splitlines()
    files = [args[index + 1] for index, value in enumerate(args) if value == "-f"]
    assert files == ["compose.yaml", "compose.jury.yaml", "compose.jury-relay.yaml"] + (
        ["compose.jury-public-demo.yaml", "compose.jury-individual.yaml"] if expected == 5 else [])
    assert args[-2:] == ["ps", "END"]


def test_unknown_mode_cannot_start_a_different_relay(tmp_path):
    script, record, env = command_fixture(tmp_path, "yes")
    result = subprocess.run(["bash", str(script), "status"], env=env, capture_output=True, text=True)
    assert result.returncode == 1 and not record.exists()


def test_validation_does_not_attach_a_second_edge_to_the_running_network(tmp_path):
    script, record, env = command_fixture(tmp_path, "1")
    result = subprocess.run(["bash", str(script), "validate"], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    calls = record.read_text(encoding="utf-8").split("END\n")
    caddy = next(call.splitlines() for call in calls if call.startswith("run\n"))
    assert caddy[caddy.index("--network") + 1] == "none"
    assert any("Caddyfile.public-demo" in value for value in caddy)
    assert not any(call.startswith("compose\n") and "\nrun\n" in call for call in calls)


def test_individual_prepare_cannot_publish_before_the_gate(tmp_path):
    script, record, env = command_fixture(tmp_path, "1")
    result = subprocess.run(["bash", str(script), "prepare"], env=env, capture_output=True, text=True)
    assert result.returncode == 1 and not record.exists()
    assert "Relay закрыт" in result.stderr

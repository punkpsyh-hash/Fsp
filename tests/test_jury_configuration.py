"""Статические регрессии отдельного временного стенда жюри."""
from pathlib import Path
import json
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


class ComposeLoader(yaml.SafeLoader):
    pass


ComposeLoader.add_constructor("!override", lambda loader, node: loader.construct_sequence(node))


def load_compose():
    return yaml.load((ROOT / "compose.jury.yaml").read_text(encoding="utf-8"), Loader=ComposeLoader)


def test_jury_compose_is_separate_and_publishes_only_edge_high_ports():
    compose = load_compose()
    services = compose["services"]

    assert compose["name"] == "fspjury"
    assert services["db"]["ports"] == []
    assert services["app"]["ports"] == []
    assert services["app"]["image"] == "fspjury-app"
    assert services["runner"]["image"] == "fspjury-runner"
    assert services["edge"]["ports"] == [
        "${FSP_JURY_LAN_ADDRESS:?Set the NAS LAN address}:18083:80",
        "${FSP_JURY_LAN_ADDRESS:?Set the NAS LAN address}:18443:443",
    ]
    assert services["edge"]["image"] == (
        "caddy:2.11.7-alpine@sha256:"
        "d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f"
    )
    for service, limits in {
        "db": ("512m", 1, 128),
        "app": ("512m", 1, 128),
        "edge": ("128m", 0.5, 128),
    }.items():
        assert (services[service]["mem_limit"], services[service]["cpus"], services[service]["pids_limit"]) == limits
    for service in ("db", "app", "runner", "edge"):
        assert services[service]["logging"] == {
            "driver": "json-file", "options": {"max-size": "1m", "max-file": "3"},
        }
    assert compose["networks"]["default"]["ipam"]["config"][0]["subnet"] == "${FSP_JURY_SUBNET:-10.254.242.0/24}"
    assert compose["networks"]["runner_net"]["ipam"]["config"][0]["subnet"] == "${FSP_JURY_RUNNER_SUBNET:-10.254.243.0/24}"


def test_jury_app_configuration_fails_closed():
    env = load_compose()["services"]["app"]["environment"]

    assert env["FSP_JURY_MODE"] == "1"
    assert env["FSP_JURY_PASSWORD"].startswith("${FSP_JURY_PASSWORD:?")
    assert env["FSP_JURY_OPERATOR_NAME"].startswith("${FSP_JURY_OPERATOR_NAME:?")
    assert env["FSP_JURY_OPERATOR_CONTACT"].startswith("${FSP_JURY_OPERATOR_CONTACT:?")
    assert env["FSP_JURY_OPERATOR_CONFIRMED"].startswith("${FSP_JURY_OPERATOR_CONFIRMED:?")
    assert env["FSP_JURY_STORAGE_COUNTRY"].startswith("${FSP_JURY_STORAGE_COUNTRY:?")
    assert env["FSP_DEMO_LOGIN"] == "0"
    assert env["FSP_MOCK_MAIL"] == "0"
    assert env["FSP_SMTP_ENABLED"] == "0"
    assert env["FSP_SMTP_HOST"] == ""
    assert env["FSP_COOKIE_SECURE"] == "1"
    assert env["FSP_FORWARDED_ALLOW_IPS"] == "${FSP_JURY_EDGE_IP:-10.254.242.10}"
    assert env["FSP_ALLOWED_HOSTS"] == "${FSP_JURY_DOMAIN:?Set the public jury hostname}"
    assert env["FSP_ALLOWED_ORIGINS"] == "https://${FSP_JURY_DOMAIN:?Set the public jury hostname}"


def test_explicit_public_demo_override_preserves_internal_and_app_boundary():
    override = yaml.load((ROOT / "compose.jury-public-demo.yaml").read_text(encoding="utf-8"), Loader=ComposeLoader)
    assert override["services"] == {"edge": {"volumes": [
        "./docker/jury/Caddyfile.public-demo:/etc/caddy/Caddyfile:ro",
    ]}}
    caddy = (ROOT / "docker/jury/Caddyfile.public-demo").read_text(encoding="utf-8")
    assert caddy.index("respond @internal 404") < caddy.index("reverse_proxy app:8470")
    assert "@internal path /internal /internal/*" in caddy
    assert "trusted_proxies static 10.254.242.1" in caddy
    assert "header_up X-Forwarded-Proto https" in caddy
    assert "admin 127.0.0.1:2019" in caddy
    assert "basic_auth" not in caddy
    # Закрытый маршрут остаётся исходным режимом, открытый требует отдельного файла.
    assert "basic_auth argon2id" in (ROOT / "docker/jury/Caddyfile.relay").read_text(encoding="utf-8")


def test_individual_registration_is_an_explicit_bounded_override():
    override = yaml.load((ROOT / "compose.jury-individual.yaml").read_text(encoding="utf-8"), Loader=ComposeLoader)
    env = override["services"]["app"]["environment"]
    assert env == {
        "FSP_JURY_INDIVIDUAL_REGISTRATION": "1",
        "FSP_JURY_MAX_INDIVIDUAL_ACCOUNTS": "200",
        "FSP_JURY_REGISTRATION_RATE_LIMIT": "5",
        "FSP_JURY_AUTH_RATE_LIMIT": "10",
    }
    base = load_compose()["services"]["app"]["environment"]
    assert "FSP_JURY_INDIVIDUAL_REGISTRATION" not in base


def test_tools_image_includes_public_and_individual_jury_overrides():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "compose.jury-public-demo.yaml" in dockerfile
    assert "compose.jury-individual.yaml" in dockerfile


def test_caddy_denies_internal_before_auth_and_exposes_only_policies():
    caddy = (ROOT / "docker/jury/Caddyfile").read_text(encoding="utf-8")

    denied = caddy.index("respond @internal 404")
    policies = caddy.index("@legal path /legal/privacy /legal/recommendations")
    auth = caddy.index("basic_auth argon2id")
    proxy = caddy.rindex("reverse_proxy app:8470")
    assert denied < policies < auth < proxy
    assert "@internal path /internal /internal/*" in caddy
    assert "{env.FSP_JURY_BASIC_AUTH_HASH}" in caddy
    assert "\n\tlog" not in caddy


def test_jury_script_requires_explicit_network_gate_and_scoped_reset():
    script = (ROOT / "scripts/jury.sh").read_text(encoding="utf-8")

    assert "--project-name \"$PROJECT_NAME\"" in script
    assert "FSP_JURY_ACTIVATE=DNS_AND_ROUTER_VERIFIED" in script
    assert "grep -Fxq \"$FSP_JURY_PUBLIC_IP\"" in script
    assert "compose down --volumes --remove-orphans" in script
    assert "reset --yes" in script
    assert "docker compose down" not in script
    assert "set +x" in script
    assert 'source "$ENV_FILE"' not in script
    assert "env_value()" in script
    assert "FSP_JURY_BASIC_AUTH_HASH='%s'" in script
    assert "FSP_JURY_BASIC_AUTH_PASSWORD='%s'" in script
    assert "app_password=\"$(random_secret)\"" in script
    assert "edge_password=\"$(random_secret)\"" in script
    assert "Пароль приложения для готовых" not in script
    assert "compose config --quiet" in script
    assert "compose config\n" not in script
    assert "config) config_summary" in script
    assert "FSP_JURY_OPERATOR_CONFIRMED='1'" in script


@pytest.mark.skipif(shutil.which("docker") is None, reason="требуется локальный Docker")
@pytest.mark.parametrize("filename", ["Caddyfile", "Caddyfile.public-demo"])
def test_caddyfile_is_accepted_by_pinned_official_caddy(filename):
    caddyfile = (ROOT / "docker/jury" / filename).resolve()
    image = load_compose()["services"]["edge"]["image"]
    result = subprocess.run([
        "docker", "run", "--rm", "--network", "none",
        "--volume", f"{caddyfile}:/etc/caddy/Caddyfile:ro",
        "--env", "FSP_JURY_DOMAIN=localhost",
        "--env", "FSP_JURY_BASIC_AUTH_USER=jury",
        "--env", (
            "FSP_JURY_BASIC_AUTH_HASH=$argon2id$v=19$m=47104,t=1,p=1$"
            "dGVzdHNhbHQxMjM0NTY3OA$QiP/RnGR4UoxYwSuMfKct5DO6ejqKMQvlpcMaFqnwh8"
        ),
        image, "caddy", "validate", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile",
    ], text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_runbook_public_availability_is_backed_by_external_receipt():
    runbook = (ROOT / "docs/61-temporary-domain-stand.md").read_text(encoding="utf-8")
    receipt_path = ROOT / "docs/release/2026-10-11-legal-submission/jury-public-http.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["result"] == "passed"
    assert receipt["origin"] == "https://fsptest.kolesnikovny.ru"
    assert receipt["credentials_logged"] is False
    assert "external to VPS/NAS" in receipt["execution"]
    assert any(check["path"] == "/" and check["actual"] == 401 for check in receipt["checks"])
    assert all(check["expected"] == check["actual"] for check in receipt["checks"])
    assert "jury-public-http.json" in runbook
    assert "5.101.153.251" in runbook
    assert "46.8.231.30" in runbook
    assert "WAN TCP 80" in runbook and "WAN TCP 443" in runbook
    assert "192.168.1.58:18083" in runbook
    assert "192.168.1.58:18443" in runbook
    assert "FSP_JURY_STORAGE_COUNTRY=RU" in runbook
    assert "docker compose config --quiet" in runbook
    assert "полный вывод\n`docker compose config`" in runbook

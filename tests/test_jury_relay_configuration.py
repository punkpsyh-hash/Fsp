"""Регрессии reviewable VPS relay без обращения к NAS или VPS."""
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


class ComposeLoader(yaml.SafeLoader):
    pass


ComposeLoader.add_constructor("!override", lambda loader, node: loader.construct_sequence(node))


def load_relay():
    return yaml.load((ROOT / "compose.jury-relay.yaml").read_text(encoding="utf-8"), Loader=ComposeLoader)


def test_relay_exposes_only_nas_loopback_and_keeps_base_runner_topology():
    services = load_relay()["services"]

    assert services["edge"]["ports"] == ["127.0.0.1:18083:80"]
    assert services["edge"]["volumes"] == ["./docker/jury/Caddyfile.relay:/etc/caddy/Caddyfile:ro"]
    assert "app" not in services
    assert "runner" not in services


def test_tunnel_is_fixed_to_loopback_reverse_forward_and_ru2_env():
    tunnel = load_relay()["services"]["tunnel"]
    command = tunnel["command"]

    assert tunnel["network_mode"] == "host"
    assert "127.0.0.1:18470:127.0.0.1:18083" in command
    assert "StrictHostKeyChecking=yes" in command
    assert "PasswordAuthentication=no" in command
    assert "ExitOnForwardFailure=yes" in command
    assert tunnel["cap_drop"] == ["ALL"]
    assert tunnel["read_only"] is True
    assert (tunnel["mem_limit"], tunnel["cpus"], tunnel["pids_limit"]) == ("64m", 0.25, 32)
    assert tunnel["logging"]["options"] == {"max-size": "1m", "max-file": "3"}
    script = (ROOT / "scripts/jury-relay-nas.sh").read_text(encoding="utf-8")
    assert "stat -c '%u'" in script and "== '10001'" in script
    assert "10.254.242.0/24" in script and "10.254.242.10" in script
    assert "prepare)" in script
    assert "db app runner edge tunnel" in script


def test_caddy_trusts_only_bridge_gateway_and_rewrites_forwarded_headers():
    caddy = (ROOT / "docker/jury/Caddyfile.relay").read_text(encoding="utf-8")

    assert "trusted_proxies static 10.254.242.1" in caddy
    assert "trusted_proxies_strict" in caddy
    assert "trusted_proxies static private_ranges" not in caddy
    assert "@internal path /internal /internal/*" in caddy
    assert caddy.count("header_up X-Forwarded-For {client_ip}") == 2
    assert caddy.count("header_up X-Forwarded-Proto https") == 2


def test_vps_configs_are_exact_vhost_loopback_only_and_fail_closed():
    http = (ROOT / "docker/jury/nginx-vps-http.conf").read_text(encoding="utf-8")
    https = (ROOT / "docker/jury/nginx-vps.conf").read_text(encoding="utf-8")
    sshd = (ROOT / "docker/jury/sshd-jury-relay.conf").read_text(encoding="utf-8")
    script = (ROOT / "scripts/jury-relay-vps.sh").read_text(encoding="utf-8")

    assert "server_name fsptest.kolesnikovny.ru;" in http
    assert "return 503;" in http
    assert "proxy_pass" not in http
    assert "proxy_pass http://127.0.0.1:18470;" in https
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in https
    assert "$proxy_add_x_forwarded_for" not in https
    assert https.count("access_log off;") == 2
    assert "AllowTcpForwarding remote" in sshd
    assert "PermitListen 127.0.0.1:18470" in sshd
    assert "GatewayPorts no" in sshd
    assert "MaxSessions 0" in sshd
    assert sshd.rstrip().endswith("Match all")
    assert 'restrict,port-forwarding,permitlisten="127.0.0.1:18470"' in script
    assert "assert_ssh_ownership" in script
    assert "certbot/certbot:v5.8.0@sha256:f70ad0ad" in script
    assert "--register-unsafely-without-email" in script
    assert "--email" not in script
    assert 'renew --cert-name "$DOMAIN"' in script
    assert "usermod --password '*'" in script

    logrotate = (ROOT / "docker/jury/logrotate-nginx-vps.conf").read_text(encoding="utf-8")
    assert "/var/log/nginx/fsptest-error.log" in logrotate
    assert "size 1M" in logrotate and "rotate 7" in logrotate


@pytest.mark.skipif(shutil.which("docker") is None, reason="требуется локальный Docker")
def test_relay_caddyfile_is_accepted_by_pinned_caddy():
    caddyfile = (ROOT / "docker/jury/Caddyfile.relay").resolve()
    image = (
        "caddy:2.11.7-alpine@sha256:"
        "d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f"
    )
    result = subprocess.run([
        "docker", "run", "--rm", "--network", "none",
        "--volume", f"{caddyfile}:/etc/caddy/Caddyfile:ro",
        "--env", "FSP_JURY_BASIC_AUTH_USER=jury",
        "--env", (
            "FSP_JURY_BASIC_AUTH_HASH=$argon2id$v=19$m=47104,t=1,p=1$"
            "dGVzdHNhbHQxMjM0NTY3OA$QiP/RnGR4UoxYwSuMfKct5DO6ejqKMQvlpcMaFqnwh8"
        ),
        image, "caddy", "validate", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile",
    ], text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr

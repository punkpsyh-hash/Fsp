"""Регрессии узкой границы доверия между Caddy и Uvicorn jury-стенда."""
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class ComposeLoader(yaml.SafeLoader):
    pass


ComposeLoader.add_constructor("!override", lambda loader, node: loader.construct_sequence(node))


def load_compose():
    return yaml.load((ROOT / "compose.jury.yaml").read_text(encoding="utf-8"), Loader=ComposeLoader)


def test_jury_app_trusts_only_fixed_edge_address():
    compose = load_compose()
    edge_ip = "${FSP_JURY_EDGE_IP:-10.254.242.10}"

    assert compose["services"]["app"]["environment"]["FSP_FORWARDED_ALLOW_IPS"] == edge_ip
    assert compose["services"]["edge"]["networks"]["default"]["ipv4_address"] == edge_ip
    assert edge_ip not in {"*", "10.254.242.0/24"}


def test_entrypoint_passes_explicit_proxy_trust_to_uvicorn():
    entrypoint = (ROOT / "scripts/entrypoint.sh").read_text(encoding="utf-8")

    assert 'FSP_FORWARDED_ALLOW_IPS="${FSP_FORWARDED_ALLOW_IPS:-127.0.0.1}"' in entrypoint
    assert "--proxy-headers" in entrypoint
    assert '--forwarded-allow-ips "$FSP_FORWARDED_ALLOW_IPS"' in entrypoint
    assert "--forwarded-allow-ips '*'" not in entrypoint

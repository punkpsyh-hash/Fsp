"""Read only the public, fixed FSP ID discovery document; never authenticate."""

import datetime
import json
import sys
import urllib.error
import urllib.request


ISSUER = "https://sso.fsp-russia.ru/realms/fsp"
DISCOVERY_URL = ISSUER + "/.well-known/openid-configuration"
MAX_BYTES = 262144
STRING_FIELDS = (
    "issuer", "authorization_endpoint", "token_endpoint", "userinfo_endpoint",
    "jwks_uri", "end_session_endpoint",
)
LIST_FIELDS = (
    "scopes_supported", "response_types_supported", "grant_types_supported",
    "code_challenge_methods_supported", "token_endpoint_auth_methods_supported",
    "subject_types_supported", "id_token_signing_alg_values_supported",
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def inspect():
    report = {
        "checked_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "discovery_url": DISCOVERY_URL,
        "provenance": {
            "portal": "https://lk.fsp-russia.ru/login",
            "portal_login_link": "https://lk.fsp-russia.ru/auth/redirect",
            "discovery_path_documentation": "https://www.keycloak.org/securing-apps/oidc-layers",
        },
        "operation": "GET public OIDC discovery only; redirects disabled; TLS verification enabled",
        "authentication_performed": False,
        "registry_access_tested": False,
        "permission_for_our_client_confirmed": False,
    }
    try:
        # No cookies, credentials, user-supplied URLs, token or userinfo calls.
        opener = urllib.request.build_opener(NoRedirect())
        request = urllib.request.Request(DISCOVERY_URL, headers={"Accept": "application/json"})
        with opener.open(request, timeout=20) as response:
            report["http_status"] = response.status
            if response.status != 200:
                raise ValueError("unexpected_http_status")
            content_type = response.headers.get_content_type()
            if content_type != "application/json" and not content_type.endswith("+json"):
                raise ValueError("unexpected_content_type")
            report["content_type"] = content_type
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("oversized_discovery_document")
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("issuer") != ISSUER:
            raise ValueError("unexpected_issuer_or_document")
        selected = {}
        for key in STRING_FIELDS:
            value = data.get(key)
            if value is None:
                continue
            if not isinstance(value, str) or len(value) > 2048:
                raise ValueError("invalid_metadata_field")
            selected[key] = value
        for key in LIST_FIELDS:
            value = data.get(key)
            if value is None:
                continue
            if not isinstance(value, list) or len(value) > 100 or any(
                not isinstance(item, str) or len(item) > 256 for item in value
            ):
                raise ValueError("invalid_metadata_field")
            selected[key] = value
        report["metadata"] = selected
        report["issuer_matches_expected"] = True
        report["pkce_s256_advertised"] = "S256" in selected.get("code_challenge_methods_supported", [])
        report["status"] = "public_discovery_verified"
        return report, 0
    except urllib.error.HTTPError as exc:
        report.update(status="http_error", http_status=exc.code)
    except Exception as exc:
        # Never print exception strings/response bodies, which may contain secrets.
        report.update(status="inspection_failed", error_type=type(exc).__name__)
    return report, 1


if __name__ == "__main__":
    result, exit_code = inspect()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(exit_code)

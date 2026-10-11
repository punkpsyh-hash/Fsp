"""Реальный HTTP через отдельный Unix socket: обычный и структурированный запрос."""
import json
import socketserver
import threading
from http.server import BaseHTTPRequestHandler

import pytest

from src.server.llm import LLMConfig, OpenAICompatible, config_from_env


def test_openai_provider_uses_unix_socket_without_dns_or_proxy(tmp_path, monkeypatch):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            received.append((self.path, self.headers.get('Authorization'), payload))
            body = json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}]}).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    path = str(tmp_path / 'model.sock')
    server = socketserver.UnixStreamServer(path, Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:1')
    provider = OpenAICompatible(LLMConfig('openai-compatible', 'http://local-model.internal/v1',
                                         'test-model', 'synthetic-test-key', socket_path=path))
    try:
        assert provider.complete('system', 'user') == '{"ok":true}'
        assert provider.complete_structured('system', 'user', {'type': 'object'}) == '{"ok":true}'
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
    assert [r[0] for r in received] == ['/v1/chat/completions'] * 2
    assert all(r[1] == 'Bearer synthetic-test-key' for r in received)
    assert 'response_format' not in received[0][2]
    assert received[1][2]['response_format']['type'] == 'json_schema'


@pytest.mark.parametrize('path', ['relative.sock', '/tmp/model', 'https://remote/model.sock'])
def test_invalid_unix_socket_configuration_is_rejected(path):
    with pytest.raises(ValueError, match='FSP_LLM_SOCKET_PATH'):
        config_from_env({'FSP_LLM_SOCKET_PATH': path})

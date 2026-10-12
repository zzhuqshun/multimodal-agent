import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from smartfill.model_api import ModelConfig, check_model


@contextmanager
def service(*, status=200, malformed=False, unknown=False, finish="stop", usage=True, redirect=False, delay=False):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append((self.command, self.path, self.headers.get("Authorization"), None))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"data": [{"id": "other" if unknown else "qwen-test"}]}).encode())

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.command, self.path, self.headers.get("Authorization"), body))
            if delay:
                time.sleep(0.1)
                return
            self.send_response(302 if redirect else status)
            if redirect:
                self.send_header("Location", self.server.base + "/leaked")
            self.end_headers()
            if malformed:
                self.wfile.write(b"not-json with private-debug-data")
            elif status != 200:
                self.wfile.write(b"private-debug-data")
            else:
                result = {"model": "qwen-test", "choices": [
                    {"message": {"role": "assistant", "content": "SMARTFILL_OK"}, "finish_reason": finish}]}
                if usage:
                    result["usage"] = {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15}
                self.wfile.write(json.dumps(result).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.base = f"http://127.0.0.1:{server.server_port}"
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.base, requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.mark.parametrize("usage", [True, False])
def test_live_http_probe_uses_fixed_prompt_and_actual_usage(usage):
    with service(usage=usage) as (base, requests):
        config = ModelConfig.from_env({
            "SMARTFILL_MODEL_BASE_URL": base + "/v1",
            "SMARTFILL_MODEL_NAME": "qwen-test", "SMARTFILL_MODEL_API_KEY": "dummy-token"})
        report = check_model(config)
    assert report["status"] == "passed" and report["probe_match"]
    assert report["usage"]["total_tokens"] == (15 if usage else None)
    assert report["elapsed_ms"] > 0
    assert len(requests) == 2
    assert requests[0][:3] == ("GET", "/v1/models", "Bearer dummy-token")
    assert requests[1][3]["chat_template_kwargs"] == {"enable_thinking": False}
    assert requests[1][3]["messages"] == [{"role": "user", "content": "Reply with exactly SMARTFILL_OK."}]
    assert "dummy-token" not in repr(config) + json.dumps(report)


@pytest.mark.parametrize("options,error", [
    ({"status": 401}, "HTTP 401"), ({"status": 500}, "HTTP 500"),
    ({"redirect": True}, "HTTP 302"), ({"malformed": True}, "invalid JSON"),
    ({"unknown": True}, "absent"), ({"finish": "length"}, "completed text"),
    ({"delay": True}, "timed out"),
])
def test_http_errors_and_truncated_responses_fail_without_payload_leak(options, error):
    with service(**options) as (base, requests):
        config = ModelConfig.from_env({"SMARTFILL_MODEL_BASE_URL": base + "/v1",
                                      "SMARTFILL_MODEL_NAME": "qwen-test",
                                      "SMARTFILL_MODEL_TIMEOUT_SECONDS": "0.02" if options.get("delay") else "120"})
        with pytest.raises(ValueError, match=error) as raised:
            check_model(config)
        assert "private-debug-data" not in str(raised.value)
        assert not any(r[1] == "/leaked" for r in requests)
        if options.get("unknown"):
            assert len(requests) == 1


@pytest.mark.parametrize("key,value", [
    ("SMARTFILL_MODEL_BASE_URL", "http://SERVER_HOST:8000/v1"),
    ("SMARTFILL_MODEL_BASE_URL", "http://user:password@localhost:8000/v1"),
    ("SMARTFILL_MODEL_BASE_URL", "file:///v1"),
    ("SMARTFILL_MODEL_BASE_URL", "http://localhost:8000/v1?key=secret"),
    ("SMARTFILL_MODEL_NAME", "DEPLOYED_MODEL_ID"),
    ("SMARTFILL_MODEL_TIMEOUT_SECONDS", "nan"),
    ("SMARTFILL_MODEL_TIMEOUT_SECONDS", "0"),
    ("SMARTFILL_MODEL_API_KEY", "dummy\r\ninjection"),
    ("SMARTFILL_MODEL_API_KEY", "无效密钥"),
])
def test_invalid_configuration_is_rejected_before_network(key, value):
    env = {"SMARTFILL_MODEL_BASE_URL": "http://127.0.0.1:18000/v1",
           "SMARTFILL_MODEL_NAME": "qwen-test", key: value}
    with pytest.raises(ValueError):
        ModelConfig.from_env(env)

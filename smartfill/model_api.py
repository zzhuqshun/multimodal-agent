"""Small OpenAI-compatible HTTP client; no model SDK or automatic .env execution."""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from http.client import HTTPException
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


@dataclass(frozen=True)
class ModelConfig:
    base_url: str
    model: str
    api_key: str = field(repr=False)
    timeout: float

    @classmethod
    def from_env(cls, environment=None):
        env = os.environ if environment is None else environment
        base = env.get("SMARTFILL_MODEL_BASE_URL", "").strip().rstrip("/")
        model = env.get("SMARTFILL_MODEL_NAME", "").strip()
        key = env.get("SMARTFILL_MODEL_API_KEY", "")
        try:
            parts = urlsplit(base)
            port = parts.port
            timeout = float(env.get("SMARTFILL_MODEL_TIMEOUT_SECONDS", "120"))
        except ValueError:
            raise ValueError("invalid model URL or timeout configuration") from None
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username or parts.password or parts.query or parts.fragment
                or parts.path != "/v1" or any(c.isspace() for c in base)
                or "SERVER_HOST" in base or port == 0):
            raise ValueError("SMARTFILL_MODEL_BASE_URL must be an HTTP(S) /v1 endpoint without credentials")
        if (not model or model == "DEPLOYED_MODEL_ID" or any(c in model for c in "\r\n")
                or any(not 32 <= ord(c) <= 126 for c in key)):
            raise ValueError("set a valid model name and single-line API key")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("model timeout must be finite and positive")
        return cls(base, model, key, timeout)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Keep credentials and requests on the configured endpoint.


def request_json(config: ModelConfig, route: str, payload=None):
    headers = {"Accept": "application/json"}
    if config.api_key:
        headers["Authorization"] = "Bearer " + config.api_key
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        headers["Content-Type"] = "application/json"
    request = Request(config.base_url + route, data=body, headers=headers)
    try:
        with build_opener(NoRedirect).open(request, timeout=config.timeout) as response:
            body = response.read(1024 * 1024 + 1)
    except HTTPError as error:
        raise ValueError(f"model service returned HTTP {error.code}; response body omitted") from None
    except (URLError, TimeoutError, OSError, HTTPException):
        raise ValueError("model service unreachable or timed out") from None
    if len(body) > 1024 * 1024:
        raise ValueError("model response exceeds the 1 MiB check limit")
    try:
        data = json.loads(body)
    except (ValueError, UnicodeError):
        raise ValueError("model service returned invalid JSON") from None
    if not isinstance(data, dict):
        raise ValueError("model service response must be a JSON object")
    return data


def check_model(config: ModelConfig) -> dict:
    """Check model registration and one fixed text prompt, never task materials."""
    started = perf_counter()
    listing = request_json(config, "/models")
    models = listing.get("data")
    if not isinstance(models, list) or not all(isinstance(m, dict) and isinstance(m.get("id"), str) for m in models):
        raise ValueError("model list has an invalid structure")
    if config.model not in {m["id"] for m in models}:
        raise ValueError("configured model is absent from the server model list")
    response = request_json(config, "/chat/completions", {
        "model": config.model,
        "messages": [{"role": "user", "content": "Reply with exactly SMARTFILL_OK."}],
        "max_tokens": 64, "temperature": 0, "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    })
    content, tokens = completed_chat(response)
    return {"status": "passed", "model_id": config.model,
            "response_model": response.get("model"), "text_response": content,
            "probe_match": content.strip() == "SMARTFILL_OK",
            "usage": tokens, "elapsed_ms": (perf_counter() - started) * 1000,
            "scope": "model registration and text connectivity only; no filling or vision evaluation"}


def completed_chat(response):
    """Validate a complete answer and actual optional token counters."""
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("chat response has an invalid choices structure")
    message = choices[0].get("message")
    if (not isinstance(message, dict) or not isinstance(message.get("content"), str)
            or not message["content"].strip() or choices[0].get("finish_reason") != "stop"):
        raise ValueError("no completed text answer; check thinking mode and output token limit")
    usage = response.get("usage")
    if usage is not None and not isinstance(usage, dict):
        raise ValueError("chat response has invalid token usage")
    tokens = {name: (usage or {}).get(name) for name in ("prompt_tokens", "completion_tokens", "total_tokens")}
    if any(v is not None and (type(v) is not int or v < 0) for v in tokens.values()):
        raise ValueError("chat response has invalid token counts")
    return message["content"], tokens

"""Small, single-attempt OpenRouter client for the source-validation review."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
GENERATION_URL = "https://openrouter.ai/api/v1/generation"
REQUEST_TIMEOUT_SECONDS = 90
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_REDACTED = "[REDACTED]"
_ENV_KEYS = frozenset({"OPENROUTER_KEY", "YOSOI_MODEL"})


@dataclass(frozen=True)
class Settings:
    """Hold the provider key in memory and expose only the normalized model."""

    api_key: str = field(repr=False)
    model: str

    @classmethod
    def from_env_file(cls, path: Path) -> Settings:
        """Read only the two supported literal assignments from a dotenv file."""
        values: dict[str, str] = {}
        with Path(path).open(encoding="utf-8") as stream:
            for raw_line in stream:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, raw_value = line.partition("=")
                name = name.strip()
                if name not in _ENV_KEYS:
                    continue
                if name in values:
                    raise ValueError(f"duplicate {name} assignment in dotenv file")
                value = raw_value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                    value = value[1:-1]
                values[name] = value
        api_key = values.get("OPENROUTER_KEY", "").strip()
        model = normalize_model(values.get("YOSOI_MODEL", ""))
        if not api_key or not model:
            raise ValueError("dotenv file must define OPENROUTER_KEY and YOSOI_MODEL")
        return cls(api_key=api_key, model=model)


def load_settings(path: Path) -> Settings:
    """Read only OPENROUTER_KEY and YOSOI_MODEL from the specified dotenv file."""
    return Settings.from_env_file(path)


def normalize_model(value: str) -> str:
    """Remove the repository's ``openrouter:`` provider prefix."""
    if not isinstance(value, str):
        raise ValueError("model setting must be a string")
    model = value.strip()
    prefix = "openrouter:"
    if model.lower().startswith(prefix):
        model = model[len(prefix) :]
    if not model or any(character.isspace() for character in model):
        raise ValueError("model setting is empty or malformed")
    return model


def _contains_secret(value: Any, secret: str) -> bool:
    if isinstance(value, str):
        return bool(secret) and secret in value
    if isinstance(value, Mapping):
        return any(
            _contains_secret(key, secret) or _contains_secret(item, secret)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_secret(item, secret) for item in value)
    return False


def _redact(value: Any, secret: str) -> Any:
    if isinstance(value, str):
        return value.replace(secret, _REDACTED) if secret else value
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = _redact(str(key), secret)
            safe[safe_key] = _redact(item, secret)
        return safe
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, tuple):
        return [_redact(item, secret) for item in value]
    return value


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _response_payload(raw: bytes, secret: str) -> Any:
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = {"raw_text": raw.decode("utf-8", errors="replace")}
    return _redact(parsed, secret)


def _response_metadata(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {
            "provider": None,
            "request_id": None,
            "model": None,
            "finish_reason": None,
            "usage": None,
        }
    choices = payload.get("choices")
    first_choice = choices[0] if isinstance(choices, list) and choices else {}
    if not isinstance(first_choice, Mapping):
        first_choice = {}
    return {
        "provider": payload.get("provider"),
        "request_id": payload.get("id"),
        "model": payload.get("model"),
        "finish_reason": first_choice.get("finish_reason"),
        "usage": payload.get("usage"),
    }


def _request_payload(
    request_body: Mapping[str, Any], settings: Settings
) -> tuple[dict[str, Any], bytes]:
    if not isinstance(request_body, Mapping):
        raise ValueError("request body must be a JSON object")
    try:
        body = json.loads(json.dumps(request_body, ensure_ascii=False))
    except (TypeError, ValueError) as error:
        raise ValueError("request body must contain JSON-compatible values") from error
    supplied_model = body.get("model")
    if (
        not isinstance(supplied_model, str)
        or normalize_model(supplied_model) != settings.model
    ):
        raise ValueError("request body model must match the configured provider model")
    body["model"] = settings.model
    if _contains_secret(body, settings.api_key):
        raise ValueError("request body contains the configured credential")
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return body, raw


def _capture_response(response: Any) -> tuple[int, bytes, bool]:
    status = getattr(response, "status", None)
    if status is None:
        status = response.getcode()
    status = int(status)
    captured = response.read(MAX_RESPONSE_BYTES + 1)
    too_large = len(captured) > MAX_RESPONSE_BYTES
    return status, captured[:MAX_RESPONSE_BYTES], too_large


def call_review(
    request_body: Mapping[str, Any],
    settings: Settings,
    output_directory: Path,
    timeout_s: float = 90,
) -> dict[str, Any]:
    """POST once, recording pre-request state and a redacted terminal result.

    Existing output directories are refused so a retry cannot accidentally send
    another POST under the same experiment identity.
    """
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, (int, float))
        or timeout_s <= 0
    ):
        raise ValueError("timeout_s must be a positive number")
    output_directory = Path(output_directory)
    if output_directory.exists():
        raise FileExistsError("provider output directory already exists")
    body, request_bytes = _request_payload(request_body, settings)
    request_body_sha256 = hashlib.sha256(request_bytes).hexdigest()
    output_directory.mkdir(parents=True, exist_ok=False)
    _write_json(
        output_directory / "request.json",
        {
            "endpoint": CHAT_COMPLETIONS_URL,
            "method": "POST",
            "body": body,
            "request_body_sha256": request_body_sha256,
        },
    )
    started_at = _timestamp()
    initial_state = {
        "status": "started",
        "started_at_utc": started_at,
        "attempts": 1,
        "request_body_sha256": request_body_sha256,
        "timeout_seconds": timeout_s,
        "maximum_response_bytes": MAX_RESPONSE_BYTES,
        "billing_outcome": "unknown_until_provider_response",
    }
    _write_json(output_directory / "state.json", initial_state)
    start_clock = time.perf_counter()
    terminal: dict[str, Any]
    payload: Any | None = None
    response_path: Path | None = None

    request = Request(
        CHAT_COMPLETIONS_URL,
        data=request_bytes,
        headers={
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            http_status, raw_response, truncated = _capture_response(response)
        response_sha256 = hashlib.sha256(raw_response).hexdigest()
        payload = _response_payload(raw_response, settings.api_key)
        response_path = output_directory / "response.raw.json"
        _write_json(response_path, payload)
        redacted_bytes = response_path.read_bytes()
        metadata = _response_metadata(payload)
        if truncated:
            status = "response_too_large"
        elif http_status >= 400:
            status = "http_error"
        elif isinstance(payload, Mapping) and payload.get("error"):
            status = "provider_error"
        elif not isinstance(payload, Mapping) or "choices" not in payload:
            status = "invalid_response"
        else:
            status = "completed"
        terminal = {
            "status": status,
            "http_status": http_status,
            "started_at_utc": started_at,
            "finished_at_utc": _timestamp(),
            "latency_seconds": time.perf_counter() - start_clock,
            "attempts": 1,
            "request_body_sha256": request_body_sha256,
            "configured_model": settings.model,
            "billing_outcome": "unknown",
            "response_bytes_captured": len(raw_response),
            "response_truncated": truncated,
            "response_sha256": response_sha256,
            "redacted_response_sha256": hashlib.sha256(redacted_bytes).hexdigest(),
            "response_file": response_path.name,
            **metadata,
            "error": _redact(payload.get("error"), settings.api_key)
            if isinstance(payload, Mapping)
            else None,
        }
    except HTTPError as error:
        raw_response, truncated = _read_http_error(error)
        response_sha256 = (
            hashlib.sha256(raw_response).hexdigest() if raw_response else None
        )
        payload = (
            _response_payload(raw_response, settings.api_key) if raw_response else None
        )
        if payload is not None:
            response_path = output_directory / "response.raw.json"
            _write_json(response_path, payload)
            redacted_bytes = response_path.read_bytes()
        else:
            redacted_bytes = b""
        metadata = _response_metadata(payload)
        terminal = {
            "status": "http_error",
            "http_status": int(error.code),
            "http_reason": _redact(str(error.reason), settings.api_key),
            "started_at_utc": started_at,
            "finished_at_utc": _timestamp(),
            "latency_seconds": time.perf_counter() - start_clock,
            "attempts": 1,
            "request_body_sha256": request_body_sha256,
            "configured_model": settings.model,
            "billing_outcome": "unknown",
            "response_bytes_captured": len(raw_response),
            "response_truncated": truncated,
            "response_sha256": response_sha256,
            "redacted_response_sha256": hashlib.sha256(redacted_bytes).hexdigest()
            if redacted_bytes
            else None,
            "response_file": None if response_path is None else response_path.name,
            **metadata,
            "error": _redact(payload.get("error"), settings.api_key)
            if isinstance(payload, Mapping)
            else None,
        }
    except (TimeoutError, URLError, ConnectionError, OSError) as error:
        terminal = {
            "status": "outcome_unknown",
            "started_at_utc": started_at,
            "finished_at_utc": _timestamp(),
            "latency_seconds": time.perf_counter() - start_clock,
            "attempts": 1,
            "request_body_sha256": request_body_sha256,
            "configured_model": settings.model,
            "billing_outcome": "unknown_request_may_have_been_accepted",
            "response_bytes_captured": 0,
            "response_truncated": False,
            "response_sha256": None,
            "redacted_response_sha256": None,
            "response_file": "response.raw.json",
            "provider": None,
            "request_id": None,
            "model": None,
            "finish_reason": None,
            "usage": None,
            "error": {
                "type": type(error).__name__,
                "message": _redact(str(error), settings.api_key),
            },
        }
    if response_path is None:
        response_path = output_directory / "response.raw.json"
        _write_json(
            response_path,
            {"response_received": False, "terminal_status": terminal["status"]},
        )
        redacted_bytes = response_path.read_bytes()
        terminal["redacted_response_sha256"] = hashlib.sha256(
            redacted_bytes
        ).hexdigest()
        terminal["response_file"] = response_path.name
    result = {
        "status": str(terminal["status"]),
        "response": payload,
        "ledger": terminal,
    }
    _write_json(output_directory / "state.json", terminal)
    _write_json(output_directory / "record.json", result)
    return result


def _read_http_error(error: HTTPError) -> tuple[bytes, bool]:
    try:
        captured = error.read(MAX_RESPONSE_BYTES + 1)
    except OSError:
        return b"", False
    truncated = len(captured) > MAX_RESPONSE_BYTES
    return captured[:MAX_RESPONSE_BYTES], truncated


def fetch_generation_stats(
    settings: Settings,
    generation_id: str,
    output_directory: Path,
) -> dict[str, Any]:
    """Optionally fetch provider generation metadata into a separate file."""
    if not isinstance(generation_id, str) or not generation_id.strip():
        raise ValueError("generation ID must be non-empty")
    output_directory = Path(output_directory)
    if not output_directory.is_dir():
        raise FileNotFoundError("provider output directory does not exist")
    stats_path = output_directory / "generation-stats.json"
    if stats_path.exists():
        raise FileExistsError("generation metadata has already been requested")
    url = f"{GENERATION_URL}?{urlencode({'id': generation_id})}"
    request = Request(
        url,
        headers={"Authorization": f"Bearer {settings.api_key}"},
        method="GET",
    )
    start_clock = time.perf_counter()
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            http_status, raw, truncated = _capture_response(response)
        payload = _response_payload(raw, settings.api_key)
        result = {
            "status": "response_too_large"
            if truncated
            else "http_error"
            if http_status >= 400
            else "completed",
            "http_status": http_status,
            "generation_id": _redact(generation_id, settings.api_key),
            "latency_seconds": time.perf_counter() - start_clock,
            "response_sha256": hashlib.sha256(raw).hexdigest(),
            "response_truncated": truncated,
            "metadata": payload,
        }
    except HTTPError as error:
        raw, truncated = _read_http_error(error)
        payload = _response_payload(raw, settings.api_key) if raw else None
        result = {
            "status": "http_error",
            "http_status": int(error.code),
            "http_reason": _redact(str(error.reason), settings.api_key),
            "generation_id": _redact(generation_id, settings.api_key),
            "latency_seconds": time.perf_counter() - start_clock,
            "response_sha256": hashlib.sha256(raw).hexdigest() if raw else None,
            "response_truncated": truncated,
            "metadata": payload,
        }
    except (TimeoutError, URLError, ConnectionError, OSError) as error:
        result = {
            "status": "outcome_unknown",
            "http_status": None,
            "generation_id": _redact(generation_id, settings.api_key),
            "latency_seconds": time.perf_counter() - start_clock,
            "response_sha256": None,
            "response_truncated": False,
            "metadata": None,
            "error": {
                "type": type(error).__name__,
                "message": _redact(str(error), settings.api_key),
            },
        }
    _write_json(stats_path, result)
    return result

"""Mock-only safety tests for the single-request OpenRouter helper."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from review_provider import CHAT_COMPLETIONS_URL, Settings, call_review, load_settings


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


def request_body() -> dict:
    return {
        "model": "openrouter:deepseek/deepseek-v4-flash",
        "messages": [{"role": "user", "content": "Check this source value."}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "review"}},
        "reasoning": {"effort": "none"},
        "temperature": 0,
        "max_tokens": 8192,
    }


class ReviewProviderTests(unittest.TestCase):
    def test_settings_parse_only_known_values_and_hide_key_from_repr(self):
        secret = "sk-test-do-not-print"
        with tempfile.TemporaryDirectory() as temp:
            env_file = Path(temp) / ".env"
            env_file.write_text(
                f'OPENROUTER_KEY="{secret}"\n'
                "YOSOI_MODEL=openrouter:deepseek/deepseek-v4-flash\n"
                "OTHER_SECRET=ignored-value\n",
                encoding="utf-8",
            )
            settings = load_settings(env_file)

        self.assertEqual(settings.model, "deepseek/deepseek-v4-flash")
        self.assertNotIn(secret, repr(settings))
        self.assertNotIn("ignored-value", repr(settings))

    def test_success_persists_started_state_and_makes_one_post(self):
        secret = "sk-test-one-request"
        settings = Settings(secret, "deepseek/deepseek-v4-flash")
        output = Path(tempfile.mkdtemp()) / "call"
        payload = {
            "id": "gen-123",
            "provider": "openrouter",
            "model": "deepseek/deepseek-v4-flash",
            "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        }
        raw = json.dumps(payload).encode()
        observed = {}

        def fake_urlopen(request, timeout):
            observed["url"] = request.full_url
            observed["timeout"] = timeout
            observed["authorization"] = request.get_header("Authorization")
            observed["started_state"] = json.loads((output / "state.json").read_text())
            return FakeResponse(raw)

        with patch("review_provider.urlopen", side_effect=fake_urlopen) as mocked:
            result = call_review(request_body(), settings, output)

        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(observed["url"], CHAT_COMPLETIONS_URL)
        self.assertEqual(observed["timeout"], 90)
        self.assertEqual(observed["authorization"], f"Bearer {secret}")
        self.assertEqual(observed["started_state"]["status"], "started")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["response"]["id"], "gen-123")
        self.assertEqual(result["ledger"]["provider"], "openrouter")
        self.assertEqual(result["ledger"]["finish_reason"], "stop")
        self.assertEqual(result["ledger"]["usage"]["prompt_tokens"], 4)
        self.assertEqual(
            result["ledger"]["response_sha256"], hashlib.sha256(raw).hexdigest()
        )
        request_text = (output / "request.json").read_text()
        request_json = json.loads(request_text)
        self.assertEqual(request_json["body"]["model"], "deepseek/deepseek-v4-flash")
        self.assertEqual(request_json["body"]["response_format"]["type"], "json_schema")
        self.assertEqual(
            result["ledger"]["request_body_sha256"],
            request_json["request_body_sha256"],
        )
        self.assertNotIn(secret, request_text)
        self.assertNotIn("Authorization", request_text)
        self.assertEqual(
            json.loads((output / "state.json").read_text())["status"], "completed"
        )
        self.assertEqual(json.loads((output / "record.json").read_text()), result)
        self.assertEqual(
            json.loads((output / "response.raw.json").read_text()), result["response"]
        )

        with self.assertRaises(FileExistsError):
            call_review(request_body(), settings, output)
        self.assertEqual(mocked.call_count, 1)

    def test_http_error_is_preserved_and_key_is_redacted(self):
        secret = "sk-test-http-error"
        settings = Settings(secret, "deepseek/deepseek-v4-flash")
        output = Path(tempfile.mkdtemp()) / "http-error"
        error_body = json.dumps(
            {"error": {"message": f"invalid token {secret}"}}
        ).encode()
        error = HTTPError(
            CHAT_COMPLETIONS_URL,
            401,
            f"unauthorized {secret}",
            {},
            io.BytesIO(error_body),
        )

        with patch("review_provider.urlopen", side_effect=error) as mocked:
            result = call_review(request_body(), settings, output)

        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(result["status"], "http_error")
        self.assertEqual(result["ledger"]["http_status"], 401)
        self.assertEqual(result["ledger"]["billing_outcome"], "unknown")
        self.assertIn("[REDACTED]", json.dumps(result["response"]))
        for name in ("request.json", "state.json", "record.json", "response.raw.json"):
            self.assertNotIn(secret, (output / name).read_text())
        saved = json.loads((output / "record.json").read_text())
        self.assertIn("unauthorized [REDACTED]", saved["ledger"]["http_reason"])

    def test_timeout_is_outcome_unknown_and_may_have_been_billed(self):
        secret = "sk-test-timeout"
        settings = Settings(secret, "deepseek/deepseek-v4-flash")
        output = Path(tempfile.mkdtemp()) / "timeout"

        with patch(
            "review_provider.urlopen", side_effect=TimeoutError(f"reset {secret}")
        ) as mocked:
            result = call_review(request_body(), settings, output, timeout_s=90)

        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertEqual(
            result["ledger"]["billing_outcome"],
            "unknown_request_may_have_been_accepted",
        )
        self.assertIn("[REDACTED]", result["ledger"]["error"]["message"])
        self.assertNotIn(secret, (output / "record.json").read_text())
        self.assertTrue((output / "response.raw.json").exists())
        self.assertIsNone(result["ledger"]["response_sha256"])


if __name__ == "__main__":
    unittest.main()

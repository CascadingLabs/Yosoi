"""Unit tests for OpenCodeModel token-usage extraction.

Decoupled companion to test_subscription_backends_observability.py: that test
pins the Langfuse-facing symptom (span attributes via real instrumentation); these pin
the cause directly — ``request()`` returns a ``RequestUsage`` populated from the
OpenCode server's ``info.tokens``, and the pure mapping handles cache/reasoning
and missing-usage responses.
"""

import httpx2
import pytest
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.usage import RequestUsage

from yosoi.integrations.opencode import OpenCodeModel, _usage_from_info

_BASE_URL = 'http://opencode.test'


def _patch_opencode_client(monkeypatch, routes: dict[str, httpx2.Response | BaseException]) -> None:
    class _Client:
        def __init__(self, *, base_url: str, timeout: int) -> None:
            self.base_url = base_url
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, path: str, json: object | None = None) -> httpx2.Response:
            response = routes[path]
            if isinstance(response, BaseException):
                raise response
            response._request = httpx2.Request('POST', f'{self.base_url}{path}')
            return response

    monkeypatch.setattr(httpx2, 'AsyncClient', _Client)


def test_usage_from_info_maps_all_token_buckets():
    info = {
        'tokens': {
            'total': 200,
            'input': 150,
            'output': 50,
            'reasoning': 12,
            'cache': {'read': 8, 'write': 4},
        },
        'cost': 0.0123,
    }
    usage = _usage_from_info(info)
    assert usage.input_tokens == 150
    assert usage.output_tokens == 50
    assert usage.cache_read_tokens == 8
    assert usage.cache_write_tokens == 4
    assert usage.details.get('reasoning_tokens') == 12


def test_usage_from_info_tolerates_missing_tokens():
    """An error response (or older server build) without `tokens` yields zeroed usage."""
    assert _usage_from_info({}) == RequestUsage()
    assert _usage_from_info({'tokens': None}) == RequestUsage()


async def test_request_populates_usage_from_server_response(monkeypatch):
    _patch_opencode_client(
        monkeypatch,
        {
            '/session': httpx2.Response(200, json={'id': 'ses_test'}),
            '/session/ses_test/message': httpx2.Response(
                200,
                json={
                    'info': {
                        'tokens': {'input': 150, 'output': 50, 'reasoning': 0, 'cache': {'read': 0, 'write': 0}},
                        'cost': 0.0123,
                    },
                    'parts': [{'type': 'text', 'text': 'hello'}],
                },
            ),
        },
    )

    model = OpenCodeModel(provider_id='openai', model_id='gpt-5-codex', base_url=_BASE_URL)
    response = await model.request([], None, ModelRequestParameters())

    assert response.usage.input_tokens == 150
    assert response.usage.output_tokens == 50


async def test_debug_span_emitted_when_sdk_debug_env_set(monkeypatch):
    """Debug obs.span is entered when YOSOI_SDK_DEBUG=1 (lines 87-88)."""

    monkeypatch.setenv('YOSOI_SDK_DEBUG', '1')
    _patch_opencode_client(
        monkeypatch,
        {
            '/session': httpx2.Response(200, json={'id': 's1'}),
            '/session/s1/message': httpx2.Response(
                200,
                json={'info': {}, 'parts': [{'type': 'text', 'text': 'ok'}]},
            ),
        },
    )

    model = OpenCodeModel(provider_id='openai', model_id='gpt-4o', base_url=_BASE_URL)
    response = await model.request([], None, ModelRequestParameters())
    assert response is not None


async def test_request_warns_and_reraises_on_http_failure(monkeypatch, mocker):
    """obs.warning is called and exception re-raised on HTTP error (lines 132-140)."""
    _patch_opencode_client(monkeypatch, {'/session': httpx2.ConnectError('refused')})

    warn = mocker.patch('yosoi.integrations.opencode.obs.warning')

    model = OpenCodeModel(provider_id='openai', model_id='gpt-4o', base_url=_BASE_URL)
    with pytest.raises(httpx2.ConnectError):
        await model.request([], None, ModelRequestParameters())

    warn.assert_called_once()


def test_usage_from_info_falls_back_when_cache_is_not_dict():
    """_usage_from_info treats non-dict cache as empty (line 163)."""
    info = {
        'tokens': {
            'input': 100,
            'output': 20,
            'cache': 'not-a-dict',  # string instead of dict → treated as {}
        }
    }
    usage = _usage_from_info(info)
    assert usage.input_tokens == 100
    assert usage.output_tokens == 20
    assert usage.cache_read_tokens is None or usage.cache_read_tokens == 0

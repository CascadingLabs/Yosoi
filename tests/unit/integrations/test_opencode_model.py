"""Unit tests for OpenCodeModel token-usage extraction.

Decoupled companion to test_subscription_backends_observability.py: that test
pins the Langfuse-facing symptom (span attributes via real instrumentation); these pin
the cause directly — ``request()`` returns a ``RequestUsage`` populated from the
OpenCode server's ``info.tokens``, and the pure mapping handles cache/reasoning
and missing-usage responses.
"""

import httpx
import respx
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.usage import RequestUsage

from yosoi.integrations.opencode import OpenCodeModel, _usage_from_info

_BASE_URL = 'http://opencode.test'


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


@respx.mock
async def test_request_populates_usage_from_server_response():
    respx.post(f'{_BASE_URL}/session').mock(return_value=httpx.Response(200, json={'id': 'ses_test'}))
    respx.post(f'{_BASE_URL}/session/ses_test/message').mock(
        return_value=httpx.Response(
            200,
            json={
                'info': {
                    'tokens': {'input': 150, 'output': 50, 'reasoning': 0, 'cache': {'read': 0, 'write': 0}},
                    'cost': 0.0123,
                },
                'parts': [{'type': 'text', 'text': 'hello'}],
            },
        )
    )

    model = OpenCodeModel(provider_id='openai', model_id='gpt-5-codex', base_url=_BASE_URL)
    response = await model.request([], None, ModelRequestParameters())

    assert response.usage.input_tokens == 150
    assert response.usage.output_tokens == 50


@respx.mock
async def test_default_suppresses_tools_enable_tools_frees_them():
    """The extractor default disables OpenCode's tools (`tools: {}`); enable_tools omits
    the key so OpenCode runs its own (incl. MCP) tool loop."""
    import json

    respx.post(f'{_BASE_URL}/session').mock(return_value=httpx.Response(200, json={'id': 'ses_test'}))
    route = respx.post(f'{_BASE_URL}/session/ses_test/message').mock(
        return_value=httpx.Response(200, json={'info': {}, 'parts': [{'type': 'text', 'text': 'ok'}]})
    )

    await OpenCodeModel(base_url=_BASE_URL).request([], None, ModelRequestParameters())
    assert json.loads(route.calls.last.request.content)['tools'] == {}

    await OpenCodeModel(base_url=_BASE_URL, enable_tools=True).request([], None, ModelRequestParameters())
    assert 'tools' not in json.loads(route.calls.last.request.content)


@respx.mock
async def test_enable_tools_exposes_tool_parts():
    """With enable_tools, the agent loop's tool parts are surfaced via last_tool_parts."""
    respx.post(f'{_BASE_URL}/session').mock(return_value=httpx.Response(200, json={'id': 'ses_test'}))
    tool_part = {'type': 'tool', 'tool': 'voidcrawl_click_by_role', 'state': {'status': 'completed'}}
    respx.post(f'{_BASE_URL}/session/ses_test/message').mock(
        return_value=httpx.Response(200, json={'info': {}, 'parts': [tool_part, {'type': 'text', 'text': 'done'}]})
    )

    model = OpenCodeModel(base_url=_BASE_URL, enable_tools=True)
    await model.request([], None, ModelRequestParameters())

    assert model.last_tool_parts == [tool_part]

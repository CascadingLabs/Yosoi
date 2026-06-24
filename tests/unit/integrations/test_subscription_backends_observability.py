"""Subscription backends emit Langfuse-bound spans 1:1 with API-backed models.

Symptom (reported): the OpenCode example showed up in Langfuse without usage —
zero tokens, no cost. The Claude SDK backend had the identical gap. Both
hardcoded an empty ``RequestUsage()`` and discarded the usage their transports
return (OpenCode: ``info.tokens``; Claude SDK: ``ResultMessage.usage``).

pydantic-ai's instrumentation only emits the ``gen_ai.usage.*`` GenAI span
attributes when usage is non-zero (see tests/unit/core/test_agent_observability.py),
and Langfuse derives a generation's tokens/cost from exactly those — so empty
usage meant an untracked generation.

Usage now lives on ``ModelResponse.usage`` at the model layer, so it is captured
on every actual LLM call regardless of how the pipeline reaches the model
(fresh discovery or partial re-discovery within an otherwise-cached run). The
fully-cached path makes no LLM call, so it has no generation to track — by
design.

These tests drive a real instrumented agent over each backend (transport
mocked) and assert the emitted ``chat`` span (a) reports the tokens the
transport returned and (b) carries the same GenAI generation attribute set a
real instrumented model emits — so Langfuse renders subscription generations
identically to API ones, and the two backends 1:1 with each other.
"""

import httpx2
import pytest
from opentelemetry.sdk.trace import ReadableSpan
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.capabilities import Instrumentation
from pydantic_ai.models.test import TestModel

from yosoi.integrations.claude_sdk import ClaudeSDKModel
from yosoi.integrations.opencode import OpenCodeModel
from yosoi.utils import observability as obs

_OC_BASE = 'http://opencode.test'

# The GenAI generation attributes Langfuse lifts onto a generation (model,
# input, output, token usage). Pinned so a pydantic-ai bump that drops one
# fails loudly. Asserted to be present on a real instrumented model (TestModel)
# below, which grounds it as the API-backed baseline rather than a guess.
_CANONICAL_GENERATION_ATTRS = {
    'gen_ai.operation.name',
    'gen_ai.system',
    'gen_ai.request.model',
    'gen_ai.response.model',
    'gen_ai.input.messages',
    'gen_ai.output.messages',
    'gen_ai.usage.input_tokens',
    'gen_ai.usage.output_tokens',
}


class _Out(BaseModel):
    title: str


@pytest.fixture
def instrumentation(mocker):
    """Wire pydantic-ai instrumentation onto the session-scoped OTel provider (conftest)."""
    obs.reset_for_tests()
    mocker.patch.object(obs.LangfuseClient, '_instance', mocker.MagicMock(tracer=mocker.MagicMock()))
    Agent.instrument_all()


async def _chat_span(model, span_exporter) -> ReadableSpan:
    """Run a fresh instrumented agent over *model* and return its single chat span."""
    span_exporter.clear()
    await Agent(model, output_type=_Out, capabilities=[Instrumentation()]).run('extract title')
    chat_spans = [s for s in span_exporter.get_finished_spans() if s.name.startswith('chat ')]
    names = [s.name for s in span_exporter.get_finished_spans()]
    assert len(chat_spans) == 1, f'expected one chat span, got: {names}'
    return chat_spans[0]


def _genai_keys(span: ReadableSpan) -> set[str]:
    return {k for k in (span.attributes or {}) if k.startswith('gen_ai.')}


def _patch_opencode_client(monkeypatch, routes: dict[str, httpx2.Response]) -> None:
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
            response._request = httpx2.Request('POST', f'{self.base_url}{path}')
            return response

    monkeypatch.setattr(httpx2, 'AsyncClient', _Client)


def _opencode_route(monkeypatch) -> None:
    """Mock OpenCode's /session + /session/{id}/message to report 150/50 tokens."""
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
                        'structured': {'title': 'hello'},
                    },
                    'parts': [{'type': 'text', 'text': '{"title": "hello"}'}],
                },
            ),
        },
    )


@pytest.mark.usefixtures('instrumentation')
async def test_opencode_run_reports_usage(span_exporter, monkeypatch):
    _opencode_route(monkeypatch)
    span = await _chat_span(
        OpenCodeModel(provider_id='openai', model_id='gpt-5-codex', base_url=_OC_BASE), span_exporter
    )
    assert span.attributes.get('gen_ai.usage.input_tokens') == 150
    assert span.attributes.get('gen_ai.usage.output_tokens') == 50


@pytest.mark.usefixtures('instrumentation')
async def test_claude_sdk_run_reports_usage(span_exporter, fake_claude_query):
    fake_claude_query(
        text='{"title": "hello"}',
        structured={'title': 'hello'},
        usage={
            'input_tokens': 150,
            'output_tokens': 50,
            'cache_read_input_tokens': 0,
            'cache_creation_input_tokens': 0,
        },
    )
    span = await _chat_span(ClaudeSDKModel(model_name='claude-opus-4-7'), span_exporter)
    assert span.attributes.get('gen_ai.usage.input_tokens') == 150
    assert span.attributes.get('gen_ai.usage.output_tokens') == 50


@pytest.mark.usefixtures('instrumentation')
async def test_subscription_spans_match_api_generation_shape(span_exporter, fake_claude_query, monkeypatch):
    """OpenCode and Claude SDK chat spans carry the same GenAI generation attrs
    as a real instrumented model — and are 1:1 with each other."""
    # API-backed baseline: a real instrumented pydantic-ai model emits the
    # canonical generation attrs. (TestModel is the repo's API stand-in — see
    # tests/unit/core/test_agent_observability.py.)
    api_keys = _genai_keys(await _chat_span(TestModel(), span_exporter))
    assert api_keys >= _CANONICAL_GENERATION_ATTRS, f'baseline missing: {_CANONICAL_GENERATION_ATTRS - api_keys}'

    _opencode_route(monkeypatch)
    opencode_keys = _genai_keys(
        await _chat_span(OpenCodeModel(provider_id='openai', model_id='gpt-5-codex', base_url=_OC_BASE), span_exporter)
    )

    fake_claude_query(
        text='{"title": "hello"}',
        structured={'title': 'hello'},
        usage={
            'input_tokens': 150,
            'output_tokens': 50,
            'cache_read_input_tokens': 0,
            'cache_creation_input_tokens': 0,
        },
    )
    claude_keys = _genai_keys(await _chat_span(ClaudeSDKModel(model_name='claude-opus-4-7'), span_exporter))

    # Each subscription backend carries the full canonical generation attr set.
    assert opencode_keys >= _CANONICAL_GENERATION_ATTRS, (
        f'opencode missing: {_CANONICAL_GENERATION_ATTRS - opencode_keys}'
    )
    assert claude_keys >= _CANONICAL_GENERATION_ATTRS, f'claude missing: {_CANONICAL_GENERATION_ATTRS - claude_keys}'

    # And the two backends are 1:1 with each other.
    assert opencode_keys == claude_keys, (
        f'backend span shape diverged: opencode-only={opencode_keys - claude_keys}, '
        f'claude-only={claude_keys - opencode_keys}'
    )

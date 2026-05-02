"""A2.1 — pin pydantic-ai's emitted span shape under propagate_attributes.

Asserts on the actual span names and GenAI semantic-convention attribute keys
that the installed ``pydantic-ai`` version emits. If pydantic-ai is bumped and
the instrumentation regresses, these assertions fail loudly.

Span shape captured during the A2.0 probe (see plan.md "Probe results"):
    agent run  (root)
      ├── chat <model_name>

GenAI attrs that appear (subset asserted here):
    agent run  : gen_ai.operation.name='invoke_agent', gen_ai.usage.input_tokens, gen_ai.usage.output_tokens
    chat test  : gen_ai.system, gen_ai.request.model, gen_ai.operation.name='chat'

Note on session/user propagation: the Langfuse SDK enriches spans with
session.id / user.id at INGESTION time (server-side), not via the OTel
client-side InMemorySpanExporter. Asserting on those attributes via the
exporter therefore proves nothing — verify them by mocking
``langfuse.propagate_attributes`` and checking call kwargs (this test) or
via the live Manual Gate D ``npx`` queries.
"""

from contextlib import contextmanager

import pytest

from yosoi.utils import observability as obs


@pytest.fixture
def agent_under_propagate(mocker):
    """Real pydantic-ai Agent + TestModel with explicit instrument_all().

    Idempotent in pydantic-ai; the explicit call here means the test does not
    depend on ``obs.configure()`` having run earlier in the session.
    """
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    obs.reset_for_tests()
    mocker.patch.object(obs.LangfuseClient, '_instance', mocker.MagicMock(tracer=mocker.MagicMock()))
    Agent.instrument_all()
    return Agent(TestModel(), instrument=True)


def _capturing_propagate(captured: list[dict]):
    @contextmanager
    def _fake(**kwargs):
        captured.append(kwargs)
        yield

    return _fake


async def test_agent_emits_pinned_span_set(agent_under_propagate, span_exporter, mocker):
    """The pinned span set ('agent run' + 'chat <model>') is emitted with expected GenAI attrs."""
    from langfuse import propagate_attributes

    captured: list[dict] = []
    mocker.patch('langfuse.propagate_attributes', _capturing_propagate(captured))

    with propagate_attributes(session_id='sess-1', user_id='shop.example.com', tags=['shop.example.com']):
        await agent_under_propagate.run('hello')

    spans = span_exporter.get_finished_spans()
    span_names = {s.name for s in spans}

    # Span set: at least one 'agent run' (root) and at least one 'chat <model>' child.
    assert 'agent run' in span_names, f'expected "agent run" span, got: {span_names}'
    chat_spans = [s for s in spans if s.name.startswith('chat ')]
    assert len(chat_spans) >= 1, f'expected a "chat <model>" span, got: {span_names}'

    # 'agent run' attrs (from probe results)
    agent_span = next(s for s in spans if s.name == 'agent run')
    assert agent_span.attributes.get('gen_ai.operation.name') == 'invoke_agent'
    assert isinstance(agent_span.attributes.get('gen_ai.usage.input_tokens'), int)
    assert isinstance(agent_span.attributes.get('gen_ai.usage.output_tokens'), int)
    assert agent_span.attributes.get('model_name') == 'test'

    # 'chat <model>' attrs (from probe results)
    chat = chat_spans[0]
    assert chat.attributes.get('gen_ai.operation.name') == 'chat'
    assert chat.attributes.get('gen_ai.system') == 'test'
    assert chat.attributes.get('gen_ai.request.model') == 'test'

    # Parent linkage: chat's parent is the agent run span.
    assert chat.parent is not None
    assert chat.parent.span_id == agent_span.context.span_id


async def test_agent_run_under_propagate_passes_kwargs_to_langfuse(agent_under_propagate, mocker):
    """propagate_attributes is called once with the expected session/user/tags kwargs.

    This is the 'session_id and user_id reach the SDK' check. The Langfuse SDK
    then enriches spans server-side; that part is verified live in Manual Gate D.
    """
    captured: list[dict] = []
    mocker.patch('langfuse.propagate_attributes', _capturing_propagate(captured))

    from langfuse import propagate_attributes

    with propagate_attributes(session_id='sess-2', user_id='blog.example.com', tags=['blog.example.com']):
        await agent_under_propagate.run('hello')

    assert len(captured) == 1
    assert captured[0] == {
        'session_id': 'sess-2',
        'user_id': 'blog.example.com',
        'tags': ['blog.example.com'],
    }

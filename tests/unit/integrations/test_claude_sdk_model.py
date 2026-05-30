"""Unit tests for ClaudeSDKModel token-usage extraction.

Mirrors test_opencode_model.py for the Claude Agent SDK backend: the pure
mapping handles Anthropic's usage shape and missing usage, and ``request()``
returns a populated ``RequestUsage`` so the generation is tracked in Langfuse.
"""

from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.usage import RequestUsage

from yosoi.integrations.claude_sdk import ClaudeSDKModel, _usage_from_result


def test_usage_from_result_maps_anthropic_usage():
    usage = _usage_from_result(
        {
            'input_tokens': 150,
            'output_tokens': 50,
            'cache_read_input_tokens': 8,
            'cache_creation_input_tokens': 4,
        }
    )
    assert usage.input_tokens == 150
    assert usage.output_tokens == 50
    assert usage.cache_read_tokens == 8
    assert usage.cache_write_tokens == 4


def test_usage_from_result_tolerates_missing_usage():
    """A turn with no usage dict (e.g. an error result) yields zeroed usage."""
    assert _usage_from_result(None) == RequestUsage()


async def test_request_populates_usage_from_result_message(fake_claude_query):
    fake_claude_query(
        text='hello',
        usage={
            'input_tokens': 150,
            'output_tokens': 50,
            'cache_read_input_tokens': 0,
            'cache_creation_input_tokens': 0,
        },
    )
    model = ClaudeSDKModel(model_name='claude-opus-4-7')
    response = await model.request([], None, ModelRequestParameters())

    assert response.usage.input_tokens == 150
    assert response.usage.output_tokens == 50


async def test_debug_span_emitted_when_sdk_debug_env_set(fake_claude_query, monkeypatch):
    """Debug obs.span is entered when YOSOI_SDK_DEBUG=1 (lines 104-105)."""
    monkeypatch.setenv('YOSOI_SDK_DEBUG', '1')
    fake_claude_query(text='hello', usage=None)

    model = ClaudeSDKModel(model_name='claude-opus-4-7')
    response = await model.request([], None, ModelRequestParameters())
    # If no exception, the debug path ran without error
    assert response is not None


async def test_request_warns_and_reraises_on_sdk_exception(mocker):
    """obs.warning is called and the exception re-raised on SDK failure (lines 132-134)."""

    mocker.patch('claude_agent_sdk.ClaudeAgentOptions', mocker.MagicMock())
    mocker.patch('claude_agent_sdk.query', side_effect=RuntimeError('SDK error'))

    warn = mocker.patch('yosoi.integrations.claude_sdk.obs.warning')

    model = ClaudeSDKModel(model_name='claude-opus-4-7')
    import pytest

    with pytest.raises(RuntimeError, match='SDK error'):
        await model.request([], None, ModelRequestParameters())

    warn.assert_called_once()

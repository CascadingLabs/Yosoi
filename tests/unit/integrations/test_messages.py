"""Tests for the pydantic-ai message flatten utility."""

from pydantic_ai.messages import ModelRequest, SystemPromptPart, UserPromptPart

from yosoi.integrations.utils.messages import flatten_messages


def test_flatten_skips_non_model_request():
    """Non-ModelRequest objects in the list are ignored (line 12: continue)."""

    class FakeResponse:
        """Stand-in for a ModelResponse or any non-request message."""

    system, user = flatten_messages([FakeResponse()])  # type: ignore[list-item]

    assert system == ''
    assert user == ''


def test_flatten_includes_instructions():
    """ModelRequest.instructions contributes to the system chunk (line 14)."""
    msg = ModelRequest(parts=[], instructions='You are a helpful assistant.')

    system, user = flatten_messages([msg])

    assert 'You are a helpful assistant.' in system
    assert user == ''


def test_flatten_includes_system_prompt_part():
    """SystemPromptPart contributes to the system chunk (line 17)."""
    msg = ModelRequest(parts=[SystemPromptPart(content='System rule.')])

    system, user = flatten_messages([msg])

    assert 'System rule.' in system
    assert user == ''


def test_flatten_combines_all_sources():
    """instructions + SystemPromptPart + UserPromptPart all land in the right chunks."""
    msg = ModelRequest(
        parts=[SystemPromptPart(content='rule'), UserPromptPart(content='question')],
        instructions='intro',
    )

    system, user = flatten_messages([msg])

    assert 'intro' in system
    assert 'rule' in system
    assert 'question' in user

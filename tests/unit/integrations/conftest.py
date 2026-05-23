"""Shared fixtures for the subscription-backed Model transport tests.

Both backends are exercised against mocked transports so no server/SDK process
or network is needed: OpenCode via ``respx`` (HTTP) in the tests themselves,
Claude SDK via the ``fake_claude_query`` fixture here (patches the SDK's
``query``/``ClaudeAgentOptions`` to emit a single ``ResultMessage``).
"""

from collections.abc import Callable
from typing import Any

import pytest


@pytest.fixture
def fake_claude_query(mocker) -> Callable[..., None]:
    """Patch ``claude_agent_sdk.query`` to emit one ResultMessage; return a configurator.

    Call the returned function with ``text`` / ``structured`` / ``usage`` to set
    what the mocked SDK turn yields. ``ClaudeAgentOptions`` is stubbed too since
    ``_call_sdk`` constructs it before querying. The fake message class is named
    ``ResultMessage`` because ``_call_sdk`` detects the turn-end via
    ``type(message).__name__ == 'ResultMessage'``.
    """

    class _Block:
        def __init__(self, text: str) -> None:
            self.text = text

    class ResultMessage:
        def __init__(self, content: list[Any], structured_output: Any, usage: dict[str, Any] | None) -> None:
            self.content = content
            self.structured_output = structured_output
            self.usage = usage

    state: dict[str, Any] = {'text': '', 'structured': None, 'usage': None}

    async def _query(*, prompt: str, options: Any):
        yield ResultMessage(
            content=[_Block(state['text'])],
            structured_output=state['structured'],
            usage=state['usage'],
        )

    mocker.patch('claude_agent_sdk.ClaudeAgentOptions', mocker.MagicMock())
    mocker.patch('claude_agent_sdk.query', _query)

    def configure(*, text: str = '', structured: Any = None, usage: dict[str, Any] | None = None) -> None:
        state.update(text=text, structured=structured, usage=usage)

    return configure

from __future__ import annotations

import sys
import types

import pytest

from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.mcp_backends import (
    ClaudeSDKBackend,
    PydanticAIBackend,
    StdioServerSpec,
    backend_for,
    validator_server_command,
)
from yosoi.core.discovery.mcp_draft import MCPDiscoveryDraft
from yosoi.utils.exceptions import LLMGenerationError


def _draft() -> MCPDiscoveryDraft:
    return MCPDiscoveryDraft(fields=[{'field': 'title', 'selector': {'value': 'h1'}, 'sample_value': 'Example'}])


async def test_pydantic_ai_backend_builds_agent_with_stdio_toolsets(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Agent:
        def __init__(self, model, *, output_type, instructions, toolsets, retries, capabilities):
            captured.update(
                model=model,
                output_type=output_type,
                instructions=instructions,
                toolsets=toolsets,
                retries=retries,
                capabilities=capabilities,
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def run(self, prompt):
            captured['prompt'] = prompt
            return types.SimpleNamespace(output=_draft())

    monkeypatch.setitem(sys.modules, 'pydantic_ai', types.SimpleNamespace(Agent=_Agent))
    monkeypatch.setattr(
        'yosoi.core.discovery.mcp_client.stdio_toolset', lambda command, args, env, id: (command, args, env, id)
    )
    monkeypatch.setattr('yosoi.utils.observability.agent_capabilities', lambda: {'caps': True})

    result = await PydanticAIBackend(model='model').run(
        instructions='system',
        user_prompt='find selectors',
        servers=[StdioServerSpec('validator', 'cmd', ('arg',), {'A': 'B'})],
    )

    assert result.fields[0].selector.value == 'h1'
    assert captured['toolsets'] == [('cmd', ('arg',), {'A': 'B'}, 'validator')]
    assert captured['retries'] == {'output': 3}
    assert captured['prompt'] == 'find selectors'


async def test_claude_sdk_backend_reads_structured_result_and_errors(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class _Options:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    ResultMessage = type('ResultMessage', (), {'structured_output': _draft().model_dump(mode='json')})

    async def _query(prompt, options):
        seen['prompt'] = prompt
        yield ResultMessage()

    monkeypatch.setitem(
        sys.modules, 'claude_agent_sdk', types.SimpleNamespace(ClaudeAgentOptions=_Options, query=_query)
    )

    server = StdioServerSpec('voidcrawl', 'uvx', ('voidcrawl',), {'TOKEN': 'x'}, ('extract', 'title'))
    result = await ClaudeSDKBackend('claude-test').run(instructions='sys', user_prompt='user', servers=[server])

    assert result.fields[0].selector.value == 'h1'
    assert seen['model'] == 'claude-test'
    assert seen['allowed_tools'] == ['mcp__voidcrawl__extract', 'mcp__voidcrawl__title']
    assert seen['prompt'] == 'user'

    async def _empty_query(prompt, options):
        if False:
            yield None

    monkeypatch.setitem(
        sys.modules, 'claude_agent_sdk', types.SimpleNamespace(ClaudeAgentOptions=_Options, query=_empty_query)
    )
    with pytest.raises(LLMGenerationError, match='no structured output'):
        await ClaudeSDKBackend('claude-test').run(instructions='sys', user_prompt='user', servers=[])


def test_validator_command_and_backend_dispatch(monkeypatch) -> None:
    monkeypatch.setattr('shutil.which', lambda _name: '/bin/yosoi-validator-mcp')
    assert validator_server_command() == ('/bin/yosoi-validator-mcp', ())
    monkeypatch.setattr('shutil.which', lambda _name: None)
    command, args = validator_server_command()
    assert command == sys.executable
    assert args == ('-m', 'yosoi.integrations.validator_mcp')

    assert backend_for(LLMConfig(provider='claude_sdk', model_name='c')).name == 'claude-sdk'

    class _OpenCodeBackend:
        name = 'opencode'

        def __init__(self, config):
            self.config = config

    monkeypatch.setitem(
        sys.modules,
        'yosoi.core.discovery.mcp_opencode',
        types.SimpleNamespace(OpenCodeBackend=_OpenCodeBackend),
    )
    assert backend_for(LLMConfig(provider='opencode', model_name='local')).name == 'opencode'

    monkeypatch.setattr('yosoi.core.discovery.mcp_backends.create_model', lambda _config: 'created')
    backend = backend_for(LLMConfig(provider='groq', model_name='llama'))
    assert backend.name == 'pydantic-ai'

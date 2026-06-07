"""Tests for MCP discovery: draft model, validator server, backend selection."""

from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.mcp_agent import MCPDiscoveryAgent, MCPDiscoveryDraft, MCPFieldFinding
from yosoi.core.discovery.mcp_backends import (
    ClaudeSDKBackend,
    OpenCodeBackend,
    PydanticAIBackend,
    StdioServerSpec,
    backend_for,
)
from yosoi.models.selectors import SelectorEntry


class _RecordingBackend:
    name = 'recording'

    def __init__(self):
        self.servers = None

    async def run(self, *, instructions, user_prompt, servers):
        self.servers = list(servers)
        self.instructions = instructions
        self.user_prompt = user_prompt
        return MCPDiscoveryDraft()


class TestDraftModel:
    def test_defaults_are_empty(self):
        draft = MCPDiscoveryDraft()

        assert draft.fields == []
        assert draft.root is None

    def test_holds_findings(self):
        draft = MCPDiscoveryDraft(
            fields=[
                MCPFieldFinding(
                    field='headline',
                    selector=SelectorEntry(type='css', value='h1.title'),
                    sample_value='Hello',
                )
            ],
            root=SelectorEntry(type='css', value='article'),
        )

        assert draft.fields[0].field == 'headline'
        assert draft.root is not None
        assert draft.root.value == 'article'


class TestBackendSelection:
    def test_provider_api_uses_pydantic_ai(self):
        cfg = LLMConfig(provider='groq', model_name='m', api_key='k')

        assert isinstance(backend_for(cfg), PydanticAIBackend)

    def test_claude_sdk_provider_uses_claude_backend(self):
        cfg = LLMConfig(provider='claude-sdk', model_name='claude-opus-4-7')

        assert isinstance(backend_for(cfg), ClaudeSDKBackend)

    def test_opencode_provider_uses_opencode_backend(self):
        cfg = LLMConfig(provider='opencode', model_name='openai/gpt-5-codex')

        assert isinstance(backend_for(cfg), OpenCodeBackend)


class TestAllowlist:
    def test_allowed_tool_ids_are_namespaced(self):
        spec = StdioServerSpec(name='voidcrawl', command='voidcrawl-mcp', tools=('eval_js', 'extract'))

        assert spec.allowed_tool_ids() == ['mcp__voidcrawl__eval_js', 'mcp__voidcrawl__extract']


class TestAgentMountsSharedServers:
    async def test_mounts_voidcrawl_and_validator(self, mocker):
        mocker.patch('yosoi.core.discovery.mcp_agent.voidcrawl_command', return_value='/usr/bin/voidcrawl-mcp')
        backend = _RecordingBackend()
        cfg = LLMConfig(provider='groq', model_name='m', api_key='k')
        agent = MCPDiscoveryAgent(cfg, backend=backend)

        await agent.discover('https://example.com', {'title': 'the title'}, {})

        names = {s.name for s in backend.servers}
        assert names == {'voidcrawl', 'yosoi_validator'}
        validator = next(s for s in backend.servers if s.name == 'yosoi_validator')
        assert validator.tools == ('check_value',)


class TestValidatorServer:
    def test_check_value_ok_and_feedback(self, monkeypatch):
        from yosoi.integrations.validator_mcp import FIELD_RULES_ENV, field_rules_env
        from yosoi.types.registry import KIND_NUMERIC, SemanticRule

        # Build the server with a numeric rule baked into the env, then exercise
        # its registered tool the way the MCP runtime would.
        monkeypatch.setenv(FIELD_RULES_ENV, field_rules_env({'score': SemanticRule(kind=KIND_NUMERIC, max_chars=10)}))
        from yosoi.integrations import validator_mcp

        rules = validator_mcp._load_rules()
        assert rules['score'].kind == KIND_NUMERIC

        validator = validator_mcp.SemanticValidator()
        assert validator.validate({'score': '42'}, rules) == []
        assert validator.validate({'score': 'no digits'}, rules) != []

"""Tests for the MCP discovery agent's output model and validator tool."""

from types import SimpleNamespace

from yosoi.core.discovery.mcp_agent import MCPDiscoveryDraft, MCPFieldFinding, _check_value
from yosoi.core.verification.semantic import SemanticValidator
from yosoi.models.selectors import SelectorEntry
from yosoi.prompts.mcp_discovery import MCPDiscoveryDeps
from yosoi.types.registry import KIND_NUMERIC, KIND_TEXT, SemanticRule


def _ctx(rules):
    deps = MCPDiscoveryDeps(
        url='https://example.com',
        fields={'score': 'numeric score'},
        field_rules=rules,
        validator=SemanticValidator(),
    )
    return SimpleNamespace(deps=deps)


class TestCheckValueTool:
    def test_ok_for_well_shaped_value(self):
        ctx = _ctx({'score': SemanticRule(kind=KIND_NUMERIC, max_chars=10)})

        assert _check_value(ctx, 'score', '42') == 'ok'

    def test_feedback_for_wrong_shape(self):
        ctx = _ctx({'score': SemanticRule(kind=KIND_NUMERIC, max_chars=10)})

        result = _check_value(ctx, 'score', 'no digits here')

        assert result != 'ok'
        assert 'score' in result

    def test_long_text_rejected_when_bounded(self):
        ctx = _ctx({'score': SemanticRule(kind=KIND_TEXT, max_chars=5)})

        result = _check_value(ctx, 'score', 'x' * 200)

        assert result != 'ok'

    def test_field_without_rule_is_ok(self):
        ctx = _ctx({})

        assert _check_value(ctx, 'score', 'anything at all') == 'ok'


class TestDraftModel:
    def test_defaults_are_empty(self):
        draft = MCPDiscoveryDraft()

        assert draft.fields == []
        assert draft.root is None
        assert draft.replay_plan.is_empty

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

"""Tests for yosoi.prompts.discovery — prompt builders and system-prompt functions."""

import pytest

from yosoi.models.contract import Contract
from yosoi.models.selectors import SelectorLevel
from yosoi.prompts.discovery import (
    DiscoveryDeps,
    DiscoveryInput,
    base_instructions,
    build_user_prompt,
    field_instructions,
    level_instructions,
    page_hints,
)


class SampleContract(Contract):
    title: str = ''
    body: str = ''


@pytest.fixture
def discovery_input():
    return DiscoveryInput(url='https://example.com', html='<html><body>Test</body></html>')


@pytest.fixture
def deps(discovery_input):
    return DiscoveryDeps(contract=SampleContract, input=discovery_input)


def _make_ctx(deps, mocker):
    ctx = mocker.Mock()
    ctx.deps = deps
    return ctx


class TestBaseInstructions:
    def test_returns_base_prompt(self, deps, mocker):
        """base_instructions returns the core identity prompt."""
        result = base_instructions(_make_ctx(deps, mocker))
        assert 'analyzing HTML' in result
        assert 'selectors' in result


class TestFieldInstructions:
    def test_includes_field_names(self, deps, mocker):
        """field_instructions includes field names from the contract."""
        result = field_instructions(_make_ctx(deps, mocker))
        assert 'title' in result
        assert 'body' in result

    def test_empty_contract_returns_empty(self, discovery_input, mocker):
        """Contract with no field_descriptions returns empty string."""

        class EmptyContract(Contract):
            pass

        empty_deps = DiscoveryDeps(contract=EmptyContract, input=discovery_input)
        result = field_instructions(_make_ctx(empty_deps, mocker))
        assert result == ''


class TestLevelInstructions:
    def test_css_only(self, deps, mocker):
        """CSS level returns CSS-only instructions."""
        deps.target_level = SelectorLevel.CSS
        result = level_instructions(_make_ctx(deps, mocker))
        assert 'CSS' in result

    def test_xpath_level(self, deps, mocker):
        """XPATH level allows CSS and XPath."""
        deps.target_level = SelectorLevel.XPATH
        result = level_instructions(_make_ctx(deps, mocker))
        assert 'XPath' in result

    def test_regex_level(self, deps, mocker):
        """REGEX level allows CSS, XPath, and regex."""
        deps.target_level = SelectorLevel.REGEX
        result = level_instructions(_make_ctx(deps, mocker))
        assert 'regex' in result

    def test_jsonld_level(self, deps, mocker):
        """JSONLD level allows all strategies."""
        deps.target_level = SelectorLevel.JSONLD
        result = level_instructions(_make_ctx(deps, mocker))
        assert 'JSON-LD' in result


class TestPageHints:
    def test_testid_hint(self, deps, mocker):
        """Detects data-testid in HTML."""
        deps.input = DiscoveryInput(url='https://x.com', html='<div data-testid="title">Hi</div>')
        result = page_hints(_make_ctx(deps, mocker))
        assert 'data-testid' in result

    def test_jsonld_hint(self, deps, mocker):
        """Detects JSON-LD structured data."""
        deps.input = DiscoveryInput(url='https://x.com', html='<script>"@type": "Article"</script>')
        result = page_hints(_make_ctx(deps, mocker))
        assert 'JSON-LD' in result

    def test_data_qa_hint(self, deps, mocker):
        """Detects data-qa test attributes."""
        deps.input = DiscoveryInput(url='https://x.com', html='<div data-qa="price">$10</div>')
        result = page_hints(_make_ctx(deps, mocker))
        assert 'data-qa' in result

    def test_no_hints(self, deps, mocker):
        """No hints for plain HTML."""
        deps.input = DiscoveryInput(url='https://x.com', html='<div>plain</div>')
        result = page_hints(_make_ctx(deps, mocker))
        assert result == ''


class TestBuildUserPrompt:
    def test_returns_json(self, discovery_input):
        """build_user_prompt returns JSON-serialized input."""
        result = build_user_prompt(discovery_input)
        assert 'https://example.com' in result
        assert 'html' in result

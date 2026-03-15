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


# ---------------------------------------------------------------------------
# Per-field discovery deps & prompt functions
# ---------------------------------------------------------------------------

from yosoi.prompts.discovery import (
    FieldDiscoveryDeps,
    field_single_base_instructions,
    field_single_field_instructions,
    field_single_level_instructions,
    field_single_page_hints,
)


@pytest.fixture
def field_deps(discovery_input):
    return FieldDiscoveryDeps(
        field_name='headline',
        field_description='Main article title',
        field_hint=None,
        input=discovery_input,
    )


def _make_field_ctx(deps, mocker):
    ctx = mocker.Mock()
    ctx.deps = deps
    return ctx


class TestFieldSingleBaseInstructions:
    def test_returns_base_prompt(self, field_deps, mocker):
        result = field_single_base_instructions(_make_field_ctx(field_deps, mocker))
        assert 'analyzing HTML' in result


class TestFieldSingleFieldInstructions:
    def test_includes_field_name_and_description(self, field_deps, mocker):
        result = field_single_field_instructions(_make_field_ctx(field_deps, mocker))
        assert 'headline' in result
        assert 'Main article title' in result

    def test_includes_hint_when_set(self, field_deps, mocker):
        field_deps.field_hint = 'Look for h1 tags'
        result = field_single_field_instructions(_make_field_ctx(field_deps, mocker))
        assert 'Look for h1 tags' in result

    def test_no_hint_when_none(self, field_deps, mocker):
        result = field_single_field_instructions(_make_field_ctx(field_deps, mocker))
        assert 'Hint' not in result

    def test_container_guidance_when_is_container(self, field_deps, mocker):
        field_deps.is_container = True
        result = field_single_field_instructions(_make_field_ctx(field_deps, mocker))
        assert 'repeating wrapper' in result

    def test_no_container_guidance_when_not_container(self, field_deps, mocker):
        field_deps.is_container = False
        result = field_single_field_instructions(_make_field_ctx(field_deps, mocker))
        assert 'repeating wrapper' not in result


class TestFieldSingleLevelInstructions:
    def test_css_only(self, field_deps, mocker):
        field_deps.target_level = SelectorLevel.CSS
        result = field_single_level_instructions(_make_field_ctx(field_deps, mocker))
        assert 'CSS' in result

    def test_xpath_level(self, field_deps, mocker):
        field_deps.target_level = SelectorLevel.XPATH
        result = field_single_level_instructions(_make_field_ctx(field_deps, mocker))
        assert 'XPath' in result

    def test_regex_level(self, field_deps, mocker):
        field_deps.target_level = SelectorLevel.REGEX
        result = field_single_level_instructions(_make_field_ctx(field_deps, mocker))
        assert 'regex' in result

    def test_jsonld_level(self, field_deps, mocker):
        field_deps.target_level = SelectorLevel.JSONLD
        result = field_single_level_instructions(_make_field_ctx(field_deps, mocker))
        assert 'JSON-LD' in result


class TestFieldSinglePageHints:
    def test_testid_hint(self, field_deps, mocker):
        field_deps.input = DiscoveryInput(url='https://x.com', html='<div data-testid="t">Hi</div>')
        result = field_single_page_hints(_make_field_ctx(field_deps, mocker))
        assert 'data-testid' in result

    def test_jsonld_hint(self, field_deps, mocker):
        field_deps.input = DiscoveryInput(url='https://x.com', html='<script>"@type": "Article"</script>')
        result = field_single_page_hints(_make_field_ctx(field_deps, mocker))
        assert 'JSON-LD' in result

    def test_data_qa_hint(self, field_deps, mocker):
        field_deps.input = DiscoveryInput(url='https://x.com', html='<div data-qa="price">$10</div>')
        result = field_single_page_hints(_make_field_ctx(field_deps, mocker))
        assert 'data-qa' in result

    def test_data_cy_hint(self, field_deps, mocker):
        field_deps.input = DiscoveryInput(url='https://x.com', html='<button data-cy="submit">Go</button>')
        result = field_single_page_hints(_make_field_ctx(field_deps, mocker))
        assert 'data-cy' in result

    def test_context_hint(self, field_deps, mocker):
        field_deps.input = DiscoveryInput(url='https://x.com', html='<script>"@context": "schema.org"</script>')
        result = field_single_page_hints(_make_field_ctx(field_deps, mocker))
        assert 'JSON-LD' in result

    def test_no_hints(self, field_deps, mocker):
        field_deps.input = DiscoveryInput(url='https://x.com', html='<div>plain</div>')
        result = field_single_page_hints(_make_field_ctx(field_deps, mocker))
        assert result == ''


class TestFieldDiscoveryDeps:
    def test_default_target_level(self, discovery_input):
        deps = FieldDiscoveryDeps(field_name='title', field_description='Title', field_hint=None, input=discovery_input)
        assert deps.target_level == SelectorLevel.CSS
        assert deps.is_container is False

    def test_custom_values(self, discovery_input):
        deps = FieldDiscoveryDeps(
            field_name='root',
            field_description='Container',
            field_hint='Look for cards',
            input=discovery_input,
            target_level=SelectorLevel.XPATH,
            is_container=True,
        )
        assert deps.field_name == 'root'
        assert deps.field_hint == 'Look for cards'
        assert deps.target_level == SelectorLevel.XPATH
        assert deps.is_container is True

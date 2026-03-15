"""Tests for DiscoveryDeps and dynamic instruction functions."""

from dataclasses import dataclass
from typing import Any

from yosoi.models.defaults import NewsArticle
from yosoi.models.selectors import SelectorLevel
from yosoi.prompts.discovery import (
    DiscoveryDeps,
    DiscoveryInput,
    base_instructions,
    field_instructions,
    level_instructions,
    page_hints,
)


# Minimal RunContext stub — instruction functions only access ctx.deps
@dataclass
class _MockCtx:
    deps: Any


def _ctx(deps: DiscoveryDeps) -> _MockCtx:
    return _MockCtx(deps=deps)


def _deps(
    *,
    level: SelectorLevel = SelectorLevel.CSS,
    html: str = '',
) -> DiscoveryDeps:
    return DiscoveryDeps(
        contract=NewsArticle,
        input=DiscoveryInput(url='https://example.com', html=html),
        target_level=level,
    )


# ---------------------------------------------------------------------------
# base_instructions
# ---------------------------------------------------------------------------


def test_base_instructions_returns_nonempty_string():
    result = base_instructions(_ctx(_deps()))
    assert isinstance(result, str)
    assert len(result) > 0


def test_base_instructions_mentions_html():
    result = base_instructions(_ctx(_deps()))
    assert 'HTML' in result


# ---------------------------------------------------------------------------
# field_instructions
# ---------------------------------------------------------------------------


def test_field_instructions_includes_field_names():
    result = field_instructions(_ctx(_deps()))
    # NewsArticle has fields like headline, body_text, etc.
    assert 'headline' in result or 'body_text' in result


def test_field_instructions_returns_string():
    result = field_instructions(_ctx(_deps()))
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# level_instructions
# ---------------------------------------------------------------------------


def test_level_instructions_css_only_mentions_css(monkeypatch):
    result = level_instructions(_ctx(_deps(level=SelectorLevel.CSS)))
    assert 'CSS' in result
    assert 'XPath' not in result


def test_level_instructions_xpath_allowed_when_standard():
    result = level_instructions(_ctx(_deps(level=SelectorLevel.XPATH)))
    assert 'XPath' in result or 'xpath' in result.lower()


def test_level_instructions_forbids_xpath_when_css_only():
    result = level_instructions(_ctx(_deps(level=SelectorLevel.CSS)))
    lower = result.lower()
    assert 'only' in lower or 'css' in lower


def test_level_instructions_all_level_allows_xpath():
    result = level_instructions(_ctx(_deps(level=SelectorLevel.JSONLD)))
    assert 'XPath' in result or 'xpath' in result.lower()


# ---------------------------------------------------------------------------
# page_hints
# ---------------------------------------------------------------------------


def test_page_hints_returns_empty_when_no_signals():
    result = page_hints(_ctx(_deps(html='<html><body><h1>Hello</h1></body></html>')))
    assert result == ''


def test_page_hints_detects_data_testid():
    html = '<div data-testid="price">$9.99</div>'
    result = page_hints(_ctx(_deps(html=html)))
    assert 'data-testid' in result


def test_page_hints_detects_json_ld():
    html = '<script type="application/ld+json">{"@type":"Product","@context":"https://schema.org"}</script>'
    result = page_hints(_ctx(_deps(html=html)))
    assert 'JSON-LD' in result or 'json' in result.lower()


def test_page_hints_returns_string():
    result = page_hints(_ctx(_deps(html='<p>plain</p>')))
    assert isinstance(result, str)

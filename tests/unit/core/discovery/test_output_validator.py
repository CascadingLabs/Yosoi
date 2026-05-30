"""Tests for the forbidden-selector output validator (enforced non-repetition)."""

from types import SimpleNamespace

import pytest
from pydantic_ai import ModelRetry

from yosoi.core.discovery.field_agent import _reject_forbidden_selectors
from yosoi.models.selectors import FieldSelectors
from yosoi.prompts.discovery import DiscoveryInput, FieldDiscoveryDeps


def _ctx(forbidden: tuple[str, ...], field_name: str = 'score'):
    deps = FieldDiscoveryDeps(
        field_name=field_name,
        field_description='desc',
        input=DiscoveryInput(url='https://x', html='<a/>'),
        forbidden_selectors=forbidden,
    )
    return SimpleNamespace(deps=deps)


def test_no_forbidden_passes_through():
    out = FieldSelectors(primary='div.card')
    assert _reject_forbidden_selectors(_ctx(()), out) is out


def test_repeating_forbidden_selector_raises_model_retry():
    out = FieldSelectors(primary='div.card')
    with pytest.raises(ModelRetry):
        _reject_forbidden_selectors(_ctx(('div.card',)), out)


def test_different_selector_is_allowed():
    out = FieldSelectors(primary='span.score::attr(data-score)')
    assert _reject_forbidden_selectors(_ctx(('div.card',)), out) is out


def test_na_is_always_allowed_even_if_forbidden():
    out = FieldSelectors(primary='NA')
    # NA means "field not present" — never treat it as a repeated selector.
    assert _reject_forbidden_selectors(_ctx(('NA',)), out) is out

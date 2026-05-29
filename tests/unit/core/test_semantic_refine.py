"""Integration tests for Pipeline._semantic_refine (semantic-validation retry loop)."""

import pytest

import yosoi as ys
from yosoi.core.pipeline import Pipeline
from yosoi.core.verification import SemanticValidator, field_rules_for_contract
from yosoi.models.selectors import SelectorLevel
from yosoi.prompts.discovery import FieldFeedback


class _PostContract(ys.Contract):
    score: int | None = ys.Field(default=None)
    title: str | None = ys.Title(default=None)


def _stub(mocker, contract=_PostContract):
    stub = Pipeline.__new__(Pipeline)
    stub.contract = contract
    stub.semantic_validator = SemanticValidator()
    stub._field_rules = field_rules_for_contract(contract)
    stub.console = mocker.MagicMock()
    stub.logger = mocker.MagicMock()
    stub.discovery = mocker.MagicMock()
    stub.selector_level = SelectorLevel.CSS
    return stub


@pytest.mark.anyio
async def test_wrong_shape_triggers_targeted_retry_with_feedback(mocker):
    stub = _stub(mocker)

    # First extraction: score grabbed whole-card text (no digit); title is fine.
    bad = {'score': 'Reply Share Save ' * 20, 'title': 'Hello world'}
    good = {'score': '42', 'title': 'Hello world'}

    fresh = {'score': {'primary': 'span.score::attr(data-score)'}}
    stub.discovery.discover_selectors = mocker.AsyncMock(return_value=fresh)
    mocker.patch.object(stub, '_verify', return_value=fresh)
    mocker.patch.object(stub, '_extract', return_value=good)

    verified = {'score': {'primary': 'div.card'}, 'title': {'primary': 'h1'}}
    extracted, new_verified = await stub._semantic_refine(
        'https://x', '<clean/>', '<raw/>', verified, None, bad, max_retries=3
    )

    # Re-discovery targeted only the failing field, forced, with FieldFeedback.
    call = stub.discovery.discover_selectors.call_args
    assert call.kwargs['stale_fields'] == {'score'}
    assert call.kwargs['force'] is True
    fb = call.kwargs['feedback']['score']
    assert isinstance(fb, FieldFeedback)
    assert 'div.card' in fb.failed_selectors  # the wrong selector is forbidden on retry
    assert 'score' in fb.message

    # The corrected selector and value win.
    assert new_verified['score']['primary'] == 'span.score::attr(data-score)'
    assert extracted['score'] == '42'


@pytest.mark.anyio
async def test_clean_extraction_skips_rediscovery(mocker):
    stub = _stub(mocker)
    stub.discovery.discover_selectors = mocker.AsyncMock()
    good = {'score': '42', 'title': 'Hello'}
    verified = {'score': {'primary': 'span.score'}, 'title': {'primary': 'h1'}}

    extracted, new_verified = await stub._semantic_refine(
        'https://x', '<clean/>', '<raw/>', verified, None, good, max_retries=3
    )

    stub.discovery.discover_selectors.assert_not_called()
    assert extracted == good
    assert new_verified == verified


@pytest.mark.anyio
async def test_refine_stops_when_rediscovery_returns_nothing(mocker):
    stub = _stub(mocker)
    bad = {'score': 'no digits here ' * 10, 'title': 'Hello'}
    stub.discovery.discover_selectors = mocker.AsyncMock(return_value=None)
    verify = mocker.patch.object(stub, '_verify')
    verified = {'score': {'primary': 'div.card'}, 'title': {'primary': 'h1'}}

    extracted, _new_verified = await stub._semantic_refine(
        'https://x', '<clean/>', '<raw/>', verified, None, bad, max_retries=3
    )

    stub.discovery.discover_selectors.assert_called_once()  # tried once, then gave up
    verify.assert_not_called()
    assert extracted == bad  # unchanged


@pytest.mark.anyio
async def test_refine_stops_when_reverify_finds_nothing(mocker):
    stub = _stub(mocker)
    bad = {'score': 'no digits here ' * 10, 'title': 'Hello'}
    stub.discovery.discover_selectors = mocker.AsyncMock(return_value={'score': {'primary': 'span.x'}})
    mocker.patch.object(stub, '_verify', return_value=None)  # re-verification fails
    extract = mocker.patch.object(stub, '_extract')
    verified = {'score': {'primary': 'div.card'}, 'title': {'primary': 'h1'}}

    extracted, _ = await stub._semantic_refine('https://x', '<clean/>', '<raw/>', verified, None, bad, max_retries=3)

    extract.assert_not_called()  # bailed before re-extracting
    assert extracted == bad


@pytest.mark.anyio
async def test_multi_item_uses_first_item_as_representative(mocker):
    stub = _stub(mocker)
    stub.discovery.discover_selectors = mocker.AsyncMock(return_value={'score': {'primary': 'span.s'}})
    mocker.patch.object(stub, '_verify', return_value={'score': {'primary': 'span.s'}})
    # After re-discovery, every item extracts a clean score.
    mocker.patch.object(stub, '_extract', return_value=[{'score': '1', 'title': 'a'}, {'score': '2', 'title': 'b'}])

    bad_items = [{'score': 'no digits here at all ' * 10, 'title': 'a'}, {'score': 'x', 'title': 'b'}]
    verified = {'score': {'primary': 'div.card'}, 'title': {'primary': 'h1'}}

    extracted, _ = await stub._semantic_refine(
        'https://x', '<clean/>', '<raw/>', verified, 'shreddit-comment', bad_items, max_retries=2
    )

    stub.discovery.discover_selectors.assert_called_once()
    assert isinstance(extracted, list)
    assert extracted[0]['score'] == '1'

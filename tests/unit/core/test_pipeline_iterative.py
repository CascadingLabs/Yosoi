"""End-to-end test for Pipeline._iterate_until_clean — the CAS-78 loop.

Synthetic scenario: the first extraction returns a "whole-card text" garbage
title (the exact failure mode reddit_ted hit on 2026-05-28). The semantic
validator flags it; the loop calls the orchestrator's partial-rediscovery
path with a feedback message; the orchestrator returns a tighter selector
and re-extraction yields a clean title. The mock orchestrator returns ONLY
the failing field's new selector (mimicking ``stale_fields=...`` semantics).

We don't invoke a real LLM — discovery is mocked. The point is to verify the
loop's plumbing: validate → re-discover with feedback → merge → verify →
re-extract, bounded by ``max_retries``.
"""

from __future__ import annotations

from typing import Any

import pytest

import yosoi as ys
from yosoi.core.pipeline import Pipeline


class _SimpleContract(ys.Contract):
    title: str = ys.Title()


def _make_stub(mocker: Any) -> Any:
    """Pipeline stub with the bare attrs needed by ``_iterate_until_clean``."""
    from tests.unit.core.conftest import make_pipeline_stub

    return make_pipeline_stub(mocker, contract=_SimpleContract)


@pytest.mark.asyncio
async def test_loop_corrects_too_broad_selector_via_feedback(mocker: Any) -> None:
    """Garbage title → validator flags → re-discovery with feedback → clean title."""
    stub = _make_stub(mocker)
    garbage = 'F' * 4_000  # way past the 500-char title cap

    # Track discover_selectors calls so we can assert the feedback shape.
    rediscover_calls: list[dict[str, Any]] = []

    async def fake_rediscover(**kwargs: Any) -> dict[str, dict[str, Any]]:
        rediscover_calls.append(kwargs)
        # Mimic orchestrator behavior with stale_fields={'title'}: return ONLY
        # the title's new (now correct) selector.
        return {'title': {'primary': {'type': 'css', 'value': 'h1.real-title'}}}

    stub.discovery.discover_selectors = fake_rediscover

    # _extract is only invoked AFTER re-discovery; the initial garbage is
    # passed straight to the loop as the `extracted` argument. So the first
    # _extract call should already return the clean value.
    mocker.patch.object(Pipeline, '_extract', return_value={'title': 'A clean post title'})
    # _verify is a passthrough for this test.
    mocker.patch.object(Pipeline, '_verify', side_effect=lambda *a, **_kw: a[2])

    initial_selectors = {'title': {'primary': {'type': 'css', 'value': 'shreddit-post'}}}
    verified, extracted = await Pipeline._iterate_until_clean(
        stub,
        url='https://x.example',
        cleaned_html='<clean/>',
        raw_html='<raw/>',
        verified=initial_selectors,
        extracted={'title': garbage},
        container_selector=None,
        max_retries=3,
        skip_verification=False,
    )

    # Re-discovery was invoked exactly once with the right feedback shape.
    assert len(rediscover_calls) == 1
    call = rediscover_calls[0]
    assert call['stale_fields'] == {'title'}
    assert call['force'] is True
    fb = call['feedback']
    assert 'title' in fb
    assert 'shreddit-post' in fb['title']  # the failed selector is quoted back
    assert 'extracted' in fb['title']

    # The merged selector reflects the new discovery.
    assert verified['title']['primary'] == {'type': 'css', 'value': 'h1.real-title'}
    # The re-extracted value passed validation.
    assert extracted == {'title': 'A clean post title'}


@pytest.mark.asyncio
async def test_loop_bounded_by_max_retries(mocker: Any) -> None:
    """If the LLM keeps emitting garbage, the loop terminates after max_retries."""
    stub = _make_stub(mocker)
    garbage = 'X' * 4_000

    rediscover_count = 0

    async def fake_rediscover(**_kw: Any) -> dict[str, dict[str, Any]]:
        nonlocal rediscover_count
        rediscover_count += 1
        # Always return a "fixed" selector — but extract still returns garbage,
        # so the loop will keep retrying until it hits the cap.
        return {'title': {'primary': {'type': 'css', 'value': 'still-bad'}}}

    stub.discovery.discover_selectors = fake_rediscover
    mocker.patch.object(Pipeline, '_extract', return_value={'title': garbage})
    mocker.patch.object(Pipeline, '_verify', side_effect=lambda *a, **_kw: a[2])

    await Pipeline._iterate_until_clean(
        stub,
        url='https://x.example',
        cleaned_html='<clean/>',
        raw_html='<raw/>',
        verified={'title': {'primary': {'type': 'css', 'value': 'shreddit-post'}}},
        extracted={'title': garbage},
        container_selector=None,
        max_retries=2,
        skip_verification=False,
    )

    assert rediscover_count == 2  # bounded


@pytest.mark.asyncio
async def test_loop_no_op_when_validation_passes(mocker: Any) -> None:
    """Validation clean on first pass → orchestrator never invoked."""
    stub = _make_stub(mocker)
    stub.discovery.discover_selectors = mocker.AsyncMock(
        side_effect=AssertionError('orchestrator must not be invoked on clean pass'),
    )
    verified_in = {'title': {'primary': 'h1'}}
    extracted_in = {'title': 'A perfectly reasonable title'}

    verified, extracted = await Pipeline._iterate_until_clean(
        stub,
        url='https://x.example',
        cleaned_html='<clean/>',
        raw_html='<raw/>',
        verified=verified_in,
        extracted=extracted_in,
        container_selector=None,
        max_retries=3,
        skip_verification=False,
    )
    assert verified is verified_in
    assert extracted is extracted_in


@pytest.mark.asyncio
async def test_loop_returns_when_rediscovery_yields_nothing(mocker: Any) -> None:
    """If the orchestrator returns None (LLM gave up), keep the prior selectors."""
    stub = _make_stub(mocker)
    stub.discovery.discover_selectors = mocker.AsyncMock(return_value=None)
    mocker.patch.object(Pipeline, '_extract')
    mocker.patch.object(Pipeline, '_verify')

    verified_in = {'title': {'primary': {'type': 'css', 'value': 'shreddit-post'}}}
    extracted_in = {'title': 'X' * 4_000}

    verified, extracted = await Pipeline._iterate_until_clean(
        stub,
        url='https://x.example',
        cleaned_html='<clean/>',
        raw_html='<raw/>',
        verified=verified_in,
        extracted=extracted_in,
        container_selector=None,
        max_retries=3,
        skip_verification=False,
    )
    # _extract and _verify never get called past the no-op rediscovery
    # because the early return fires first.
    assert verified is verified_in
    assert extracted is extracted_in


@pytest.mark.asyncio
async def test_loop_handles_multi_item_extraction_using_first_item(mocker: Any) -> None:
    """Multi-item: validator grades the first item; loop merges per-field fixes."""
    stub = _make_stub(mocker)

    async def fake_rediscover(**_kw: Any) -> dict[str, dict[str, Any]]:
        return {'title': {'primary': {'type': 'css', 'value': 'h1.title'}}}

    stub.discovery.discover_selectors = fake_rediscover
    # Return list: first item fails (too long), second is fine. Validator only
    # grades the first → triggers re-discovery → re-extract returns clean list.
    outputs = [
        [{'title': 'Y' * 4_000}, {'title': 'X' * 4_000}],
        [{'title': 'good A'}, {'title': 'good B'}],
    ]

    def fake_extract(*args: Any, **_kw: Any) -> Any:
        return outputs.pop(0)

    mocker.patch.object(Pipeline, '_extract', side_effect=fake_extract)
    mocker.patch.object(Pipeline, '_verify', side_effect=lambda *a, **_kw: a[2])

    _verified, extracted = await Pipeline._iterate_until_clean(
        stub,
        url='https://x.example',
        cleaned_html='<clean/>',
        raw_html='<raw/>',
        verified={'title': {'primary': {'type': 'css', 'value': 'shreddit-post'}}},
        extracted=[{'title': 'Y' * 4_000}, {'title': 'X' * 4_000}],
        container_selector='.card',
        max_retries=2,
        skip_verification=False,
    )
    assert isinstance(extracted, list)
    assert extracted == [{'title': 'good A'}, {'title': 'good B'}]


@pytest.mark.asyncio
async def test_FieldIssue_message_reaches_the_feedback_dict(mocker: Any) -> None:
    """End-to-end check that the validator's reason text round-trips into the
    feedback payload the orchestrator sees."""
    stub = _make_stub(mocker)

    seen_feedback: dict[str, str] = {}

    async def capture_rediscover(**kwargs: Any) -> dict[str, dict[str, Any]]:
        seen_feedback.update(kwargs['feedback'])
        return {'title': {'primary': 'h1.fixed'}}

    stub.discovery.discover_selectors = capture_rediscover
    mocker.patch.object(Pipeline, '_extract', side_effect=[{'title': 'OK'}])
    mocker.patch.object(Pipeline, '_verify', side_effect=lambda *a, **_kw: a[2])

    await Pipeline._iterate_until_clean(
        stub,
        url='https://x.example',
        cleaned_html='<clean/>',
        raw_html='<raw/>',
        verified={'title': {'primary': {'type': 'css', 'value': 'shreddit-post'}}},
        extracted={'title': 'F' * 4_000},
        container_selector=None,
        max_retries=2,
        skip_verification=False,
    )
    assert 'title' in seen_feedback
    msg = seen_feedback['title']
    # The validator's diagnosis appears in the feedback message.
    assert 'extracted' in msg
    assert 'shreddit-post' in msg
    # And the rubric pointer is present (site-agnostic — no shreddit-specific text).
    assert 'RULE 1' in msg

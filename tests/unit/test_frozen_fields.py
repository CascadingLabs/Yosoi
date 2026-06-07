"""Tests for yosoi_frozen enforcement (CAS-123)."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from yosoi import types as ys
from yosoi.models.contract import Contract
from yosoi.models.snapshot import CacheVerdict, SelectorSnapshot, SnapshotStatus

# ── test contracts ────────────────────────────────────────────────────────────


class FrozenFieldContract(Contract):
    title: str = ys.Title(description='Title')
    author: str = ys.Field(frozen=True, description='Author — never re-discovered')


class NoFrozenContract(Contract):
    title: str = ys.Title(description='Title')
    body: str = ys.BodyText(description='Body')


# ── Contract.frozen_fields() ──────────────────────────────────────────────────


class TestFrozenFields:
    def test_frozen_field_detected(self):
        assert 'author' in FrozenFieldContract.frozen_fields()

    def test_non_frozen_field_not_detected(self):
        assert 'title' not in FrozenFieldContract.frozen_fields()

    def test_no_frozen_fields_empty_set(self):
        assert NoFrozenContract.frozen_fields() == set()


# ── pipeline frozen guard ─────────────────────────────────────────────────────


def _make_snapshot(selector: str = 'h1') -> SelectorSnapshot:
    return SelectorSnapshot(
        primary=selector,
        discovered_at=datetime.now(timezone.utc),
        status=SnapshotStatus.ACTIVE,
    )


def _make_pipeline_stub(mocker):
    """Return a minimal pipeline stub with FrozenFieldContract."""
    stub = mocker.MagicMock()
    stub.contract = FrozenFieldContract
    stub._contract_spec_cache = None
    stub.selector_level = 1  # CSS
    stub.console = mocker.MagicMock()
    stub._url_start = time.monotonic()
    stub.logger = mocker.MagicMock()
    stub.storage = mocker.MagicMock()
    stub.storage.record_verdict = mocker.AsyncMock()
    stub.tracker = mocker.MagicMock()
    stub.tracker.record_url = mocker.AsyncMock(return_value=mocker.MagicMock())
    return stub


class TestFrozenGuardInPipeline:
    """The frozen guard lives in _evaluate_cached_verdicts.

    We test it indirectly by calling the real pipeline._evaluate_cached_verdicts
    and checking that frozen stale fields are moved to fresh_fields.
    """

    def test_frozen_field_excluded_from_stale(self, mocker):
        """A frozen field with a cached selector must NOT appear in stale_fields,
        even when the verifier reports drift."""
        from yosoi.core.pipeline import Pipeline

        stub = _make_pipeline_stub(mocker)

        # Simulate verdicts: title=FRESH, author=STALE (drift detected)
        stub._verify_per_field = mocker.MagicMock(
            return_value={
                'title': CacheVerdict.FRESH,
                'author': CacheVerdict.STALE,  # drift! but frozen
            }
        )

        snapshots = {
            'title': _make_snapshot('h1.title'),
            'author': _make_snapshot('.author'),  # author is in cache
        }
        stub.storage.load_snapshots = mocker.AsyncMock(return_value=snapshots)

        # Track what _extract_all_fresh was called with
        captured_fresh: set[str] = set()

        def _extract_all_fresh_spy(url, domain, fetcher, raw_html, snaps, fresh_fields, fmt, *, root_span=None):
            captured_fresh.update(fresh_fields)
            return mocker.MagicMock()

        stub._extract_all_fresh = _extract_all_fresh_spy

        import asyncio

        # Call the real method but bind it to our stub
        asyncio.run(
            Pipeline._evaluate_cached_verdicts(
                stub,
                url='https://example.com',
                domain='example.com',
                fetcher=mocker.MagicMock(),
                raw_html='<html></html>',
                cleaned_html='<html></html>',
                snapshots=snapshots,
                format_to_use=['json'],
                root_span=None,
            )
        )

        # author was stale, but frozen → must be in fresh_fields, not stale
        assert 'author' in captured_fresh, 'Frozen field with cached selector should never be re-discovered'

    def test_non_frozen_stale_field_triggers_partial_rediscovery(self, mocker):
        """A non-frozen stale field must remain in stale_fields."""
        from yosoi.core.pipeline import Pipeline

        stub = _make_pipeline_stub(mocker)
        stub.contract = NoFrozenContract  # no frozen fields

        stub._verify_per_field = mocker.MagicMock(
            return_value={
                'title': CacheVerdict.FRESH,
                'body': CacheVerdict.STALE,  # drift, not frozen
            }
        )

        snapshots = {
            'title': _make_snapshot('h1'),
            'body': _make_snapshot('p'),
        }
        stub.storage.load_snapshots = mocker.AsyncMock(return_value=snapshots)

        captured_stale: set[str] = set()

        async def _partial_spy(
            url,
            domain,
            raw_html,
            cleaned_html,
            fetcher,
            snaps,
            fresh,
            stale,
            fmt,
            max_discovery_retries=3,
            *,
            root_span=None,
        ):
            captured_stale.update(stale)

        stub._partial_rediscovery = _partial_spy

        import asyncio

        asyncio.run(
            Pipeline._evaluate_cached_verdicts(
                stub,
                url='https://example.com',
                domain='example.com',
                fetcher=mocker.MagicMock(),
                raw_html='<html></html>',
                cleaned_html='<html></html>',
                snapshots=snapshots,
                format_to_use=['json'],
                root_span=None,
            )
        )

        assert 'body' in captured_stale, 'Non-frozen stale field must stay stale'

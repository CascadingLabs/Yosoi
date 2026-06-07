"""Regression tests for the W2 profile-cascade primitive.

Covers:
* :class:`BotDetectionError` carrying the new ``identity_id`` / ``captcha_kind``
  attribution kwargs (and the legacy 3-positional-arg call sites staying valid).
* :class:`IdentityCascade` ordering / dedup / preference.
* :class:`IdentityFetcherPool` lazy-start + LRU eviction.
* :func:`run_cascade` rotating identities on ``BotDetectionError`` (mock
  fetchers), winning, persisting nothing here, and failing fast on exhaustion.

No real Chrome / voidcrawl: fetchers are mock objects raising / returning
canned results.

per-IP vs per-profile isolation EXPERIMENT (design note)
--------------------------------------------------------
The cascade emits the signals the isolation experiment needs but does not run
it here. Two crossed trials decide the rotation key (the scarce trusted profile
must not be burned on a bad IP):

* Trial A — hold IP, vary profile: fixed egress, K identities differing only in
  ``profile_dir`` (one trusted + fresh), same N queries each; record first-block
  query index + ``indicators``/``captcha_kind`` per identity. Zero new infra,
  ships first; answers "is the trusted profile the differentiator on Google?".
* Trial B — hold profile, vary IP: one ``profile_dir``, K identities differing
  only in ``proxy``, same load; record block onset per IP. Gated on a proxy pool
  existing (none threaded today).

Read-out: block tracks profile regardless of IP -> per-profile; tracks IP
regardless of profile -> per-IP; both -> joint identity (rotate the PAIR).
Instrument via the per-(identity, query-index) block log this module's
``identity_id`` + ``captcha_kind`` produce; serialize headful runs for the
~750MB/process budget.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from yosoi.core.fetcher.identity import (
    BrowserIdentity,
    IdentityCascade,
    IdentityFetcherPool,
    run_cascade,
)
from yosoi.utils.exceptions import BotDetectionError

# ---------------------------------------------------------------------------
# BotDetectionError attribution kwargs
# ---------------------------------------------------------------------------


def test_bot_detection_error_legacy_positional_still_valid() -> None:
    """The 3-positional-arg signature (every existing raise site) is preserved."""
    err = BotDetectionError('https://x.com', 403, ['captcha'])
    assert err.identity_id is None
    assert err.captcha_kind is None
    assert err.status_code == 403


def test_bot_detection_error_carries_identity_and_captcha() -> None:
    err = BotDetectionError('https://x.com', 200, ['cf-marker'], identity_id='trusted', captcha_kind='recaptcha')
    assert err.identity_id == 'trusted'
    assert err.captcha_kind == 'recaptcha'
    assert '[identity=trusted]' in str(err)
    assert '[captcha=recaptcha]' in str(err)


def test_bot_detection_error_marker_without_captcha_is_its_own_bucket() -> None:
    """A soft block (markers, no named captcha) keeps captcha_kind None — distinct signal."""
    err = BotDetectionError('https://x.com', 200, ['cf-marker'], identity_id='id1')
    assert err.indicators == ['cf-marker']
    assert err.captcha_kind is None
    assert '[captcha=' not in str(err)


# ---------------------------------------------------------------------------
# IdentityCascade
# ---------------------------------------------------------------------------


def test_cascade_requires_at_least_one_identity() -> None:
    with pytest.raises(ValueError, match='at least one'):
        IdentityCascade(())


def test_cascade_rejects_duplicate_ids() -> None:
    with pytest.raises(ValueError, match='duplicate'):
        IdentityCascade((BrowserIdentity(id='a'), BrowserIdentity(id='a')))


def test_cascade_ordered_default_keeps_order() -> None:
    c = IdentityCascade((BrowserIdentity(id='a'), BrowserIdentity(id='b'), BrowserIdentity(id='c')))
    assert [i.id for i in c.ordered()] == ['a', 'b', 'c']


def test_cascade_ordered_prefers_winner_first() -> None:
    c = IdentityCascade((BrowserIdentity(id='a'), BrowserIdentity(id='b'), BrowserIdentity(id='c')))
    assert [i.id for i in c.ordered(prefer='c')] == ['c', 'a', 'b']


def test_cascade_ordered_unknown_prefer_is_ignored() -> None:
    c = IdentityCascade((BrowserIdentity(id='a'), BrowserIdentity(id='b')))
    assert [i.id for i in c.ordered(prefer='zzz')] == ['a', 'b']


# ---------------------------------------------------------------------------
# Mock fetcher + factory
# ---------------------------------------------------------------------------


class _MockFetcher:
    """Stand-in for _VoidCrawlFetcher: records close, no real browser."""

    def __init__(self, identity: BrowserIdentity) -> None:
        self.identity = identity
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _make_pool(max_live: int = 3) -> tuple[IdentityFetcherPool, dict[str, _MockFetcher]]:
    started: dict[str, _MockFetcher] = {}

    async def factory(identity: BrowserIdentity, base_kwargs: dict) -> _MockFetcher:  # type: ignore[type-arg]
        f = _MockFetcher(identity)
        started[identity.id] = f
        return f

    pool = IdentityFetcherPool(factory=factory, max_live=max_live)  # type: ignore[arg-type]
    return pool, started


# ---------------------------------------------------------------------------
# IdentityFetcherPool — lazy start + LRU eviction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pool_lazy_starts_and_reuses() -> None:
    pool, _started = _make_pool()
    ident = BrowserIdentity(id='a')
    f1 = await pool.get(ident)
    f2 = await pool.get(ident)
    assert f1 is f2  # reused, not restarted
    assert pool.live_ids == ['a']


@pytest.mark.asyncio
async def test_pool_evicts_lru_when_over_cap() -> None:
    pool, started = _make_pool(max_live=2)
    fa = await pool.get(BrowserIdentity(id='a'))
    await pool.get(BrowserIdentity(id='b'))
    # Touch 'a' so 'b' becomes the LRU.
    await pool.get(BrowserIdentity(id='a'))
    await pool.get(BrowserIdentity(id='c'))  # over cap -> evict LRU ('b')
    assert pool.live_ids == ['a', 'c']
    assert started['b'].closed is True
    assert fa.closed is False


@pytest.mark.asyncio
async def test_pool_close_closes_all() -> None:
    pool, started = _make_pool()
    await pool.get(BrowserIdentity(id='a'))
    await pool.get(BrowserIdentity(id='b'))
    await pool.close()
    assert all(f.closed for f in started.values())
    assert pool.live_ids == []


@pytest.mark.asyncio
async def test_pool_rejects_zero_cap() -> None:
    async def _noop_factory(identity: BrowserIdentity, base_kwargs: dict) -> object:  # type: ignore[type-arg]
        return object()

    with pytest.raises(ValueError, match='max_live'):
        IdentityFetcherPool(factory=_noop_factory, max_live=0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# run_cascade — rotation on block
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, html: str | None) -> None:
        self.html = html


@pytest.mark.asyncio
async def test_run_cascade_first_identity_wins() -> None:
    pool, _ = _make_pool()
    cascade = IdentityCascade((BrowserIdentity(id='a'), BrowserIdentity(id='b')))
    calls: list[str] = []

    async def do_fetch(fetcher: object, ident: BrowserIdentity) -> _Result:
        calls.append(ident.id)
        return _Result('<html>ok</html>')

    result, winner = await run_cascade(cascade=cascade, pool=pool, do_fetch=do_fetch)  # type: ignore[arg-type]
    assert winner.id == 'a'
    assert result.html == '<html>ok</html>'
    assert calls == ['a']  # second identity never tried


@pytest.mark.asyncio
async def test_run_cascade_rotates_past_blocked_identity() -> None:
    pool, _ = _make_pool()
    cascade = IdentityCascade((BrowserIdentity(id='fresh'), BrowserIdentity(id='trusted'), BrowserIdentity(id='proxy')))
    calls: list[str] = []

    async def do_fetch(fetcher: object, ident: BrowserIdentity) -> _Result:
        calls.append(ident.id)
        if ident.id in ('fresh', 'trusted'):
            raise BotDetectionError('https://google.com', 200, ['recaptcha'], identity_id=ident.id)
        return _Result('<html>serp</html>')

    result, winner = await run_cascade(cascade=cascade, pool=pool, do_fetch=do_fetch)  # type: ignore[arg-type]
    assert calls == ['fresh', 'trusted', 'proxy']
    assert winner.id == 'proxy'
    assert result.html == '<html>serp</html>'


@pytest.mark.asyncio
async def test_run_cascade_prefers_cached_winner_first() -> None:
    pool, _ = _make_pool()
    cascade = IdentityCascade((BrowserIdentity(id='a'), BrowserIdentity(id='b'), BrowserIdentity(id='c')))
    calls: list[str] = []

    async def do_fetch(fetcher: object, ident: BrowserIdentity) -> _Result:
        calls.append(ident.id)
        return _Result('<html>ok</html>')

    _result, winner = await run_cascade(cascade=cascade, pool=pool, do_fetch=do_fetch, prefer='c')  # type: ignore[arg-type]
    assert winner.id == 'c'
    assert calls == ['c']  # cached winner retried first, won immediately


@pytest.mark.asyncio
async def test_run_cascade_exhaustion_raises_fail_fast() -> None:
    """Every identity blocked -> the last BotDetectionError propagates (no fallback)."""
    pool, _ = _make_pool()
    cascade = IdentityCascade((BrowserIdentity(id='a'), BrowserIdentity(id='b')))
    calls: list[str] = []

    async def do_fetch(fetcher: object, ident: BrowserIdentity) -> _Result:
        calls.append(ident.id)
        raise BotDetectionError('https://x.com', 200, ['blocked'], identity_id=ident.id)

    with pytest.raises(BotDetectionError) as exc_info:
        await run_cascade(cascade=cascade, pool=pool, do_fetch=do_fetch)  # type: ignore[arg-type]
    # reraise=True surfaces the LAST identity's block, attributed.
    assert exc_info.value.identity_id == 'b'
    assert calls == ['a', 'b']


@pytest.mark.asyncio
async def test_run_cascade_index_does_not_desync_on_distinct_identities() -> None:
    """Cursor binds the NEXT identity per attempt — never the same one twice."""
    pool, _ = _make_pool()
    idents = tuple(BrowserIdentity(id=f'id{i}') for i in range(4))
    cascade = IdentityCascade(idents)
    seen: list[str] = []

    async def do_fetch(fetcher: object, ident: BrowserIdentity) -> _Result:
        seen.append(ident.id)
        if ident.id != 'id3':
            raise BotDetectionError('https://x.com', 200, ['b'], identity_id=ident.id)
        return _Result('<html>ok</html>')

    _result, winner = await run_cascade(cascade=cascade, pool=pool, do_fetch=do_fetch)  # type: ignore[arg-type]
    assert seen == ['id0', 'id1', 'id2', 'id3']  # each exactly once, in order
    assert winner.id == 'id3'


# ---------------------------------------------------------------------------
# Real _VoidCrawlFetcher._do_fetch — block attribution inside acquire() block
# ---------------------------------------------------------------------------


class _FakeAcquire:
    """Async-context-manager stand-in for pool.acquire()."""

    def __init__(self, tab: object) -> None:
        self._tab = tab

    async def __aenter__(self) -> object:
        return self._tab

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakePool:
    def __init__(self, tab: object) -> None:
        self._tab = tab

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self._tab)


class _FakeBlockingTab:
    """Live-tab stub: goto no-ops, detect_captcha returns a named captcha."""

    def __init__(self, captcha: str | None) -> None:
        self._captcha = captcha
        self.detect_captcha_calls = 0

    async def goto(self, url: str, timeout: float = 30.0) -> None:
        return None

    async def detect_captcha(self) -> str | None:
        self.detect_captcha_calls += 1
        return self._captcha


@pytest.mark.asyncio
async def test_do_fetch_attributes_block_to_identity_and_captcha(mocker) -> None:  # type: ignore[no-untyped-def]
    """A block on a real _do_fetch carries identity_id + captcha_kind (probed live)."""
    from yosoi.core.fetcher.voiddriver import HeadlessFetcher

    ident = BrowserIdentity(id='trusted', headful=True)
    fetcher = HeadlessFetcher(identity=ident, min_content_length=10)
    tab = _FakeBlockingTab(captcha='recaptcha')
    fetcher._pool = _FakePool(tab)

    # Probe returns blocking HTML (long enough to pass the content-length gate so
    # we reach the bot-detection check, which then flags it).
    blocking_html = '<html><body>' + ('verify you are human ' * 30) + '</body></html>'
    mocker.patch.object(fetcher, '_fetch_with_probe', return_value=blocking_html)
    mocker.patch(
        'yosoi.core.fetcher.voiddriver.capture_ax_snapshot',
        new=mocker.AsyncMock(return_value=None),
    )
    # Force the marker heuristic to flag a block with explicit indicators.
    mocker.patch.object(
        fetcher,
        '_check_for_bot_detection',
        return_value=(True, ['captcha challenge']),
    )

    import time

    with pytest.raises(BotDetectionError) as exc_info:
        await fetcher._do_fetch('https://google.com/search', time.time(), 'cascade:trusted')

    err = exc_info.value
    assert err.identity_id == 'trusted'  # attributed to the pinned identity
    assert err.captcha_kind == 'recaptcha'  # probed on the LIVE tab, before release
    assert err.indicators == ['captcha challenge']  # html-marker signal kept distinct
    assert tab.detect_captcha_calls == 1


@pytest.mark.asyncio
async def test_do_fetch_soft_marker_block_has_none_captcha(mocker) -> None:  # type: ignore[no-untyped-def]
    """Soft block (markers, no DOM captcha) -> captcha_kind None, its own bucket."""
    from yosoi.core.fetcher.voiddriver import HeadlessFetcher

    ident = BrowserIdentity(id='fresh')
    fetcher = HeadlessFetcher(identity=ident, min_content_length=10)
    tab = _FakeBlockingTab(captcha=None)  # DOM probe finds nothing
    fetcher._pool = _FakePool(tab)

    blocking_html = '<html><body>' + ('blocked ' * 30) + '</body></html>'
    mocker.patch.object(fetcher, '_fetch_with_probe', return_value=blocking_html)
    mocker.patch(
        'yosoi.core.fetcher.voiddriver.capture_ax_snapshot',
        new=mocker.AsyncMock(return_value=None),
    )
    mocker.patch.object(fetcher, '_check_for_bot_detection', return_value=(True, ['cf-marker']))

    import time

    with pytest.raises(BotDetectionError) as exc_info:
        await fetcher._do_fetch('https://x.com', time.time(), 'cascade:fresh')

    err = exc_info.value
    assert err.identity_id == 'fresh'
    assert err.captcha_kind is None  # no named captcha despite the marker block
    assert err.indicators == ['cf-marker']


@pytest.mark.asyncio
async def test_browser_config_kwargs_threads_identity(mocker) -> None:  # type: ignore[no-untyped-def]
    """Identity proxy/profile_dir/locale/headful are threaded into BrowserConfig kwargs."""
    from yosoi.core.fetcher.voiddriver import HeadlessFetcher

    class _FakeBrowserConfig:
        model_fields: ClassVar[dict[str, None]] = {
            'proxy': None,
            'locale': None,
            'timezone_id': None,
            'extra_args': None,
            'user_agent': None,
        }

    ident = BrowserIdentity(
        id='trusted',
        profile_dir='/tmp/clone-profile',
        proxy='http://1.2.3.4:8080',
        locale='en-US',
        timezone_id='America/New_York',
        headful=True,
    )
    fetcher = HeadlessFetcher(identity=ident)
    kwargs = fetcher._browser_config_kwargs(_FakeBrowserConfig)

    assert kwargs['headless'] is False  # identity forced headful over the class default
    assert kwargs['proxy'] == 'http://1.2.3.4:8080'
    assert kwargs['locale'] == 'en-US'
    assert kwargs['timezone_id'] == 'America/New_York'
    assert '--user-data-dir=/tmp/clone-profile' in kwargs['extra_args']
    assert '--profile-directory=Default' in kwargs['extra_args']

"""Unit tests for the DFS crawl frontier: canonical identity, budgets, and persistence."""

from __future__ import annotations

import pytest

from yosoi.core.crawler.frontier import CrawlFrontier, FrontierEntry, canonicalize_url


# ── canonicalize_url ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('https://Example.COM/a/../b?z=2&a=1', 'https://example.com/b?a=1&z=2'),
        ('https://example.com:443/x', 'https://example.com/x'),
        ('http://example.com:80/', 'http://example.com/'),
        ('https://example.com:8443/x', 'https://example.com:8443/x'),
        ('https://example.com/dir/', 'https://example.com/dir/'),
        ('https://example.com', 'https://example.com/'),
    ],
)
def test_canonicalize_url_normalizes(raw: str, expected: str) -> None:
    assert canonicalize_url(raw) == expected


@pytest.mark.parametrize(
    'raw',
    [
        'ftp://example.com/file',
        'mailto:someone@example.com',
        'https://',
        'https://example.com:99999/x',  # invalid port raises ValueError internally
        'not a url',
    ],
)
def test_canonicalize_url_rejects_non_crawlable(raw: str) -> None:
    assert canonicalize_url(raw) is None


# ── push / reserve / commit ───────────────────────────────────────────────────
def _frontier(**kwargs: object) -> CrawlFrontier:
    defaults: dict[str, object] = {
        'session_id': 'test-session',
        'max_depth': 2,
        'max_pages': 5,
        'politeness_delay': 0.0,
        'persist': False,
    }
    defaults.update(kwargs)
    return CrawlFrontier(**defaults)  # type: ignore[arg-type]


def test_push_dedups_on_canonical_identity() -> None:
    frontier = _frontier()

    assert frontier.push('https://Example.com/a?b=2&a=1', depth=0) is True
    assert frontier.push('https://example.com/a?a=1&b=2', depth=0) is False
    assert frontier.seen_count == 1


def test_push_rejects_beyond_max_depth_and_bad_urls() -> None:
    frontier = _frontier(max_depth=1)

    assert frontier.push('https://example.com/deep', depth=2) is False
    assert frontier.push('ftp://example.com/x', depth=0) is False
    assert frontier.pending_count == 0


def test_push_many_preserves_listed_order_under_lifo_pop() -> None:
    frontier = _frontier()
    entries = [
        FrontierEntry(url='https://example.com/first', depth=1),
        FrontierEntry(url='https://example.com/second', depth=1),
    ]

    assert frontier.push_many(entries) == 2

    batch = frontier.reserve_batch(1)
    assert [entry.url for entry in batch] == ['https://example.com/first']


def test_reserve_batch_respects_remaining_budget_and_commit_states() -> None:
    frontier = _frontier(max_pages=2)
    frontier.push('https://example.com/a', depth=0)
    frontier.push('https://example.com/b', depth=0)
    frontier.push('https://example.com/c', depth=0)

    batch = frontier.reserve_batch(10)
    assert len(batch) == 2
    assert frontier.in_flight_count == 2
    assert frontier.reserve_batch(10) == []

    frontier.commit(batch[0].url, 'succeeded')
    frontier.commit(batch[1].url, 'failed')
    frontier.commit('https://example.com/x-unknown', 'policy_blocked')
    frontier.commit('not a url', 'succeeded')

    assert frontier.pages_fetched == 1
    assert frontier.failed_count == 1
    assert frontier.policy_blocked_count == 1
    assert frontier.in_flight_count == 0
    assert frontier.reserve_batch(0) == []


def test_reserve_batch_empty_after_budget_spent() -> None:
    frontier = _frontier(max_pages=1)
    frontier.push('https://example.com/a', depth=0)
    batch = frontier.reserve_batch(1)
    frontier.commit(batch[0].url, 'succeeded')
    frontier.push('https://example.com/b', depth=0)

    assert frontier.reserve_batch(1) == []


# ── persistence round-trip ────────────────────────────────────────────────────
async def test_save_and_load_round_trip(tmp_path, mocker) -> None:
    mocker.patch('yosoi.core.crawler.frontier.init_yosoi', return_value=tmp_path)

    frontier = CrawlFrontier(session_id='resume-test', max_depth=2, max_pages=10, persist=True)
    frontier.push('https://example.com/done', depth=0)
    frontier.push('https://example.com/pending', depth=1, source_url='https://example.com/done')
    batch = frontier.reserve_batch(2)
    done = next(entry for entry in batch if entry.url.endswith('/done'))
    frontier.commit(done.url, 'succeeded')
    await frontier.save()

    resumed = CrawlFrontier(session_id='resume-test', max_depth=2, max_pages=10, persist=True)

    assert resumed.pages_fetched == 1
    assert resumed.seen_count == 2
    # the un-committed in-flight entry is requeued for the resumed crawl
    requeued = resumed.reserve_batch(5)
    assert [entry.url for entry in requeued] == ['https://example.com/pending']
    assert requeued[0].source_url == 'https://example.com/done'


def test_load_tolerates_corrupt_state_file(tmp_path, mocker) -> None:
    mocker.patch('yosoi.core.crawler.frontier.init_yosoi', return_value=tmp_path)
    (tmp_path / 'corrupt-test.json').write_text('{not json', encoding='utf-8')

    frontier = CrawlFrontier(session_id='corrupt-test', max_depth=1, max_pages=2, persist=True)

    assert frontier.seen_count == 0
    assert frontier.pending_count == 0


# ── politeness ────────────────────────────────────────────────────────────────
async def test_respect_politeness_delays_same_host(mocker) -> None:
    frontier = _frontier(politeness_delay=0.05)
    sleep = mocker.patch('yosoi.core.crawler.frontier.asyncio.sleep', new=mocker.AsyncMock())

    await frontier.respect_politeness('https://example.com/a')
    await frontier.respect_politeness('https://example.com/b')

    sleep.assert_awaited_once()
    assert 0 < sleep.await_args.args[0] <= 0.05


async def test_respect_politeness_noop_when_disabled_or_hostless(mocker) -> None:
    frontier = _frontier(politeness_delay=0.0)
    await frontier.respect_politeness('https://example.com/a')  # returns before host tracking

    delayed = _frontier(politeness_delay=0.05)
    await delayed.respect_politeness('not a url')  # canonicalize fails -> no host -> no-op
    assert delayed._last_fetch_by_host == {}

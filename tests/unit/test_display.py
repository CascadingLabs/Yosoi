"""Tests for public terminal display helpers."""

from __future__ import annotations

import io
from datetime import datetime

import pytest
from rich.console import Console

import yosoi as ys
from yosoi.core.crawler.coordinator import CrawlJob, CrawlResult, CrawlRunSummary
from yosoi.core.crawler.links import CrawlLink
from yosoi.display import show
from yosoi.reporting.display import RichCrawlProgress

pytestmark = pytest.mark.unit


def _capture() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, width=200, force_terminal=False), buf


def _terminal_capture() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, width=200, force_terminal=True, color_system='truecolor'), buf


def test_show_auto_renders_list_of_records_as_table() -> None:
    console, buf = _capture()
    rows = [{'name': 'Forge Hammer', 'price': 12.5}, {'name': 'Tome', 'available': True}]

    show(rows, console=console)

    out = buf.getvalue()
    assert 'name' in out
    assert 'price' in out
    assert 'available' in out
    assert 'Forge Hammer' in out
    assert 'Tome' in out


def test_show_renders_url_record_cells_as_terminal_hyperlinks() -> None:
    console, buf = _terminal_capture()

    show([{'url': 'https://example.test/story'}], console=console)

    out = buf.getvalue()
    assert '\x1b]8;id=' in out
    assert ';https://example.test/story\x1b\\' in out


def test_show_is_available_from_public_lazy_api() -> None:
    console, buf = _capture()

    ys.show([{'name': 'A'}], console=console)

    assert 'A' in buf.getvalue()


def test_show_auto_renders_url_grouped_records() -> None:
    console, buf = _capture()

    show({'https://example.test/a': [{'name': 'A'}], 'https://example.test/b': []}, console=console)

    out = buf.getvalue()
    assert 'https://example.test/a' in out
    assert 'https://example.test/b' in out
    assert 'name' in out
    assert 'A' in out
    assert '(no rows)' in out


def test_show_auto_renders_url_and_contract_grouped_records() -> None:
    console, buf = _capture()

    show({'https://example.test': {'Product': [{'name': 'Anvil'}]}}, console=console)

    out = buf.getvalue()
    assert 'https://example.test' in out
    assert 'Product' in out
    assert 'Anvil' in out


def test_show_json_uses_stable_json_view_for_non_native_values() -> None:
    console, buf = _capture()

    show({'seen_at': datetime(2026, 1, 2, 3, 4, 5)}, format='json', console=console)

    out = buf.getvalue()
    assert '"seen_at"' in out
    assert '2026-01-02 03:04:05' in out


def test_show_plain_prints_literals_without_markup() -> None:
    console, buf = _capture()

    show('[bold]literal[/bold]', format='plain', console=console)

    assert '[bold]literal[/bold]' in buf.getvalue()


def test_show_title_prints_before_value() -> None:
    console, buf = _capture()

    show([{'name': 'A'}], title='Products', console=console)

    out = buf.getvalue()
    assert out.index('Products') < out.index('name')


def test_show_renders_page_fingerprint() -> None:
    console, buf = _capture()
    fp = ys.fingerprint(_page('A', 5))

    show(fp, console=console)

    out = buf.getvalue()
    assert 'Fingerprint' in out
    assert 'skeleton' in out
    assert 'semantic' in out


def test_show_renders_fingerprint_comparison() -> None:
    console, buf = _capture()

    show(_page('A', 5), fingerprint=_page('A', 7), console=console)

    out = buf.getvalue()
    assert 'Fingerprint comparison' in out
    assert 'score' in out
    assert 'same_shape' in out
    assert 'yes' in out


def test_show_renders_crawl_summary() -> None:
    console, buf = _capture()
    summary = CrawlRunSummary(
        pages_fetched=1,
        attempted_urls=2,
        unique_urls_seen=3,
        policy_blocked=1,
        wall_time=0.25,
        results=[
            CrawlResult(
                job=CrawlJob(url='https://qscrape.dev/l1/news/articles', depth=0, source_url=None, batch_index=0),
                status='succeeded',
                discovered_links=(
                    CrawlLink(url='https://qscrape.dev/l1/news/articles/story-one', text='Story One', score=0.8),
                ),
                content_type='text/html; charset=utf-8',
            ),
            CrawlResult(
                job=CrawlJob(
                    url='https://qscrape.dev/l1/news/articles/story-one',
                    depth=1,
                    source_url='https://qscrape.dev/l1/news/articles',
                    batch_index=1,
                ),
                status='succeeded',
                content_type='text/html; charset=utf-8',
            ),
            CrawlResult(
                job=CrawlJob(url='https://qscrape.dev/login', depth=1, source_url=None, batch_index=2),
                status='policy_blocked',
            ),
        ],
    )

    show(summary, console=console)

    out = buf.getvalue()
    assert 'Crawl summary' in out
    assert 'pages fetched' in out
    assert 'https://qscrape.dev/l1/news/articles' in out
    assert 'Crawl path coverage' in out
    assert '/l1' in out
    assert 'Crawl content types' in out
    assert 'text/html' in out
    assert 'Discovered links' in out
    assert 'https://qscrape.dev/l1/news/articles/story-one' in out
    assert 'Representative inventory URLs' in out
    assert 'Neutral scrape target URLs' in out
    assert 'Policy blocked' in out


def test_show_caps_long_crawl_lanes() -> None:
    console, buf = _capture()
    summary = CrawlRunSummary(
        pages_fetched=25,
        attempted_urls=25,
        unique_urls_seen=25,
        wall_time=0.25,
        results=[
            CrawlResult(
                job=CrawlJob(url=f'https://example.test/{idx}', depth=0, source_url=None, batch_index=idx),
                status='succeeded',
            )
            for idx in range(25)
        ],
    )

    show(summary, console=console)

    out = buf.getvalue()
    assert 'https://example.test/0' in out
    assert 'https://example.test/19' in out
    assert 'https://example.test/20' not in out
    assert '... 5 more' in out


def test_show_renders_crawl_urls_as_terminal_hyperlinks() -> None:
    console, buf = _terminal_capture()
    summary = CrawlRunSummary(
        pages_fetched=1,
        attempted_urls=1,
        unique_urls_seen=1,
        wall_time=0.25,
        results=[
            CrawlResult(
                job=CrawlJob(url='https://example.test/story', depth=0, source_url=None, batch_index=0),
                status='succeeded',
            )
        ],
    )

    show(summary, console=console)

    out = buf.getvalue()
    assert '\x1b]8;id=' in out
    assert ';https://example.test/story\x1b\\' in out


def test_live_crawl_progress_renders_urls_as_terminal_hyperlinks() -> None:
    console, buf = _terminal_capture()
    progress = RichCrawlProgress(console=console)
    summary = CrawlRunSummary()

    progress.start(seeds=('https://example.test/story',), summary=summary, config=object())
    console.print(progress._render())

    out = buf.getvalue()
    assert '\x1b]8;id=' in out
    assert ';https://example.test/story\x1b\\' in out


def test_show_table_rejects_non_table_values() -> None:
    console, _ = _capture()

    with pytest.raises(TypeError):
        show('hello', format='table', console=console)


def test_show_rejects_unknown_format() -> None:
    console, _ = _capture()

    with pytest.raises(ValueError, match='Unknown show format'):
        show([], format='xml', console=console)  # type: ignore[arg-type]


def test_show_does_not_mutate_input() -> None:
    console, _ = _capture()
    rows = [{'b': 1}, {'a': 2}]
    before = [dict(row) for row in rows]

    show(rows, console=console)

    assert rows == before


def _page(label: str, count: int) -> str:
    cards = ''.join(f'<article><h2>{label}</h2><p>${i}</p></article>' for i in range(count))
    return f'<html><body><main><h1>Catalog</h1><section class="catalog">{cards}</section></main></body></html>'

"""Tests for generic page acquisition runtime."""

from __future__ import annotations

from rich.console import Console

from yosoi.core.page import PageAcquisition, PageSnapshot
from yosoi.models.results import FetchResult
from yosoi.policy import PagePolicy


class FakeFetcher:
    def __init__(self, html: str, *, headers: dict[str, str] | None = None) -> None:
        self.html = html
        self.headers = headers
        self.calls: list[str] = []

    async def fetch(self, url: str, **_kwargs: object) -> FetchResult:
        self.calls.append(url)
        return FetchResult(url=url, html=self.html, status_code=200, fetch_time=0.01, headers=self.headers)


async def test_page_acquisition_returns_snapshot_with_raw_and_cleaned_html() -> None:
    html = '<html><body><nav>Chrome</nav><main><h1>Story</h1><p>Body</p></main></body></html>'
    fetcher = FakeFetcher(html)
    runtime = PagePolicy(fetcher_type='simple', clean_html=True).to_runtime_config()

    snapshot = await PageAcquisition(runtime, console=Console(quiet=True)).acquire(
        'https://example.com/story',
        fetcher=fetcher,
    )

    assert isinstance(snapshot, PageSnapshot)
    assert snapshot.raw_html == html
    assert snapshot.cleaned_html is not None
    assert 'Chrome' not in snapshot.cleaned_html
    assert snapshot.html_for_discovery == snapshot.cleaned_html
    assert snapshot.fingerprint is not None
    assert snapshot.observation is not None


async def test_page_acquisition_can_leave_html_raw_by_policy() -> None:
    html = '<html><body><nav>Keep</nav><main><h1>Story</h1></main></body></html>'
    runtime = PagePolicy(clean_html=False).to_runtime_config()

    snapshot = await PageAcquisition(runtime, console=Console(quiet=True)).acquire(
        'https://example.com/story',
        fetcher=FakeFetcher(html),
    )

    assert snapshot.cleaned_html is None
    assert snapshot.html_for_discovery == html


async def test_page_acquisition_skips_cleaning_for_xml_feeds() -> None:
    xml = '<?xml version="1.0" encoding="UTF-8"?><rss><channel><title>Feed</title></channel></rss>'
    runtime = PagePolicy(clean_html=True).to_runtime_config()

    snapshot = await PageAcquisition(runtime, console=Console(quiet=True)).acquire(
        'https://example.com/feed.xml',
        fetcher=FakeFetcher(xml, headers={'content-type': 'application/xml'}),
    )

    assert snapshot.raw_html == xml
    assert snapshot.cleaned_html is None
    assert snapshot.html_for_discovery == xml


def test_page_policy_projects_runtime_without_runtime_choice() -> None:
    runtime = PagePolicy(fetcher_type='headless', timeout_seconds=12, allow_redirects=False).to_runtime_config()

    assert runtime.fetcher_type == 'headless'
    assert runtime.timeout_seconds == 12
    assert runtime.allow_redirects is False

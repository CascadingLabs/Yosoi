"""VoidDriver integration tests.

Two groups, both gated behind @pytest.mark.browser_integration (YOSOI_INTEGRATION=1):

  Static (L1) — Python's built-in HTTP server serves tests/fixtures/html/.
    Deterministic, offline, verifies the core Chrome → _do_fetch() → FetchResult path.

  Live qscrape.dev L2 — Real JS-framework pages (React / Vue / Svelte) served by
    qscrape.dev.  The static HTML stubs contain ~600 chars of text; VoidDriver must
    wait for framework hydration before the full DOM is available.  These tests assert
    that the rendered output is meaningfully richer than the raw stub.
"""

from __future__ import annotations

import functools
import http.server
import threading

import pytest

from tests.fixtures import FIXTURES_HTML_DIR, MOUNTAINHOME_HOME, VAULTMART_CATALOG

# ---------------------------------------------------------------------------
# Session-scoped local HTTP server
# ---------------------------------------------------------------------------


@pytest.fixture(scope='session')
def static_server():
    """Serve tests/fixtures/html/ over HTTP on a random port for the whole session."""
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler,
        directory=str(FIXTURES_HTML_DIR),
    )
    server = http.server.HTTPServer(('127.0.0.1', 0), handler)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f'http://127.0.0.1:{port}'
    yield base_url

    server.shutdown()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.browser_integration
async def test_voiddriver_fetches_static_html(static_server, no_sandbox, tmp_path):
    """VoidDriver fetches a locally-served page through real Chromium."""
    from yosoi.core.fetcher.voiddriver import HeadlessFetcher

    url = f'{static_server}/{MOUNTAINHOME_HOME}'

    async with HeadlessFetcher(console=None, timeout=30, no_sandbox=no_sandbox) as driver:
        result = await driver.fetch(url)

    assert result.html is not None, f'Expected HTML content, got None (status={result.status_code})'
    assert 'MOUNTAINHOME HERALD' in result.html
    assert result.status_code == 200


@pytest.mark.browser_integration
async def test_voiddriver_multi_item_page(static_server, no_sandbox, tmp_path):
    """VoidDriver fetches the VaultMart catalog and returns the full product grid HTML."""
    from yosoi.core.fetcher.voiddriver import HeadlessFetcher

    url = f'{static_server}/{VAULTMART_CATALOG}'

    async with HeadlessFetcher(console=None, timeout=30, no_sandbox=no_sandbox) as driver:
        result = await driver.fetch(url)

    assert result.html is not None
    assert 'product-card' in result.html
    assert len(result.html) > 5_000


@pytest.mark.browser_integration
async def test_voiddriver_browse_yields_eval_capable_tab(static_server, no_sandbox, tmp_path):
    """VoidDriver.browse() yields a tab that supports JS evaluation."""
    from yosoi.core.fetcher.voiddriver import HeadlessFetcher

    url = f'{static_server}/{MOUNTAINHOME_HOME}'

    async with HeadlessFetcher(console=None, timeout=30, no_sandbox=no_sandbox) as driver, driver.browse(url) as tab:
        title = await tab.eval_js('document.title')

    assert isinstance(title, str)
    assert 'Mountainhome' in title or len(title) > 0


# ---------------------------------------------------------------------------
# qscrape.dev L2 — JS-framework rendered pages
# The static HTML stub is ~600 chars; after browser hydration the full DOM
# should contain the actual page content rendered by React / Vue / Svelte.
# ---------------------------------------------------------------------------

# Minimum rendered text length that proves JS executed successfully.
# Raw static stubs are ~500-600 chars; a hydrated page is several thousand.
_L2_MIN_RENDERED_CHARS = 3_000


@pytest.mark.browser_integration
async def test_l2_news_articles_renders_article_list(no_sandbox):
    """qscrape.dev L2 news articles page hydrates to show the article grid."""
    from yosoi.core.fetcher.voiddriver import HeadlessFetcher

    async with HeadlessFetcher(console=None, timeout=60, no_sandbox=no_sandbox) as driver:
        result = await driver.fetch('https://qscrape.dev/l2/news/articles')

    assert result.html is not None
    # Must be substantially richer than the raw static stub (~600 chars)
    assert len(result.html) > _L2_MIN_RENDERED_CHARS, (
        f'L2 page appears un-hydrated: only {len(result.html)} chars (expected >{_L2_MIN_RENDERED_CHARS})'
    )
    # Framework-rendered article listing should contain article data
    html_lower = result.html.lower()
    assert any(kw in html_lower for kw in ('article', 'headline', 'mountainhome', 'mhh')), (
        'Expected article content after JS hydration'
    )


@pytest.mark.browser_integration
async def test_l2_eshop_catalog_renders_product_grid(no_sandbox):
    """qscrape.dev L2 eshop catalog page hydrates to show product cards."""
    from yosoi.core.fetcher.voiddriver import HeadlessFetcher

    async with HeadlessFetcher(console=None, timeout=60, no_sandbox=no_sandbox) as driver:
        result = await driver.fetch('https://qscrape.dev/l2/eshop/catalog')

    assert result.html is not None
    assert len(result.html) > _L2_MIN_RENDERED_CHARS
    html_lower = result.html.lower()
    assert any(kw in html_lower for kw in ('product', 'price', 'vaultmart', 'catalog')), (
        'Expected product content after JS hydration'
    )


@pytest.mark.browser_integration
async def test_l2_scoretap_renders_scores_table(no_sandbox):
    """qscrape.dev L2 ScoreTap page hydrates to show match scores and standings."""
    from yosoi.core.fetcher.voiddriver import HeadlessFetcher

    async with HeadlessFetcher(console=None, timeout=60, no_sandbox=no_sandbox) as driver:
        result = await driver.fetch('https://qscrape.dev/l2/scoretap/')

    assert result.html is not None
    assert len(result.html) > _L2_MIN_RENDERED_CHARS
    html_lower = result.html.lower()
    assert any(kw in html_lower for kw in ('score', 'match', 'team', 'scoretap')), (
        'Expected scores/match content after JS hydration'
    )


@pytest.mark.browser_integration
async def test_l2_news_browse_extracts_via_js(no_sandbox):
    """browse() + eval_js works on a JS-framework page — can query rendered DOM."""
    from yosoi.core.fetcher.voiddriver import HeadlessFetcher

    async with (
        HeadlessFetcher(console=None, timeout=60, no_sandbox=no_sandbox) as driver,
        driver.browse('https://qscrape.dev/l2/news/articles') as tab,
    ):
        # Count how many article elements the framework rendered
        count = await tab.eval_js(
            'document.querySelectorAll(\'[class*="article"], [class*="story"], [data-article-id]\').length'
        )

    assert isinstance(count, int | float)
    assert count > 0, f'Expected at least one article element after hydration, got {count}'

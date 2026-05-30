"""Pipeline integration tests using qscrape.dev HTML fixtures.

Exercises the full cleaner → discovery → extractor chain with realistic HTML
from Mountainhome Herald (news) and VaultMart (e-commerce catalog) without
hitting any live network or real LLM.

Key paths covered:
  - Fresh discovery with real HTML via mocked discovery returning fixture-aware selectors
  - Cached-selector path with skip_verification=True (pipeline.py lines 830-835)
  - Cached-selector fetch+verify path (pipeline.py lines 785-800)
  - Multi-item extraction from a product catalog (`.product-card` container)
"""

from __future__ import annotations

from datetime import datetime, timezone

import yosoi as ys
from tests.fixtures import MOUNTAINHOME_HOME, VAULTMART_CATALOG, load_html
from yosoi.core.pipeline import Pipeline
from yosoi.models.contract import Contract
from yosoi.models.defaults import NewsArticle
from yosoi.models.results import ContentMetadata, FetchResult
from yosoi.models.snapshot import SelectorSnapshot, SnapshotStatus

# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class ProductContract(Contract):
    """Matches VaultMart product cards."""

    name: str = ys.Field(hint='product name')
    price: str = ys.Field(hint='product price')


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _snapshot(primary: str, fallback: str | None = None) -> SelectorSnapshot:
    return SelectorSnapshot(
        primary=primary,
        fallback=fallback,
        discovered_at=_NOW,
        last_verified_at=_NOW,
        status=SnapshotStatus.ACTIVE,
    )


def _patch_common(mocker, tmp_path):
    """Apply patches common to every pipeline test in this module."""
    selector_dir = tmp_path / 'selectors'
    content_dir = tmp_path / 'content'
    js_scripts_dir = tmp_path / 'js_scripts'
    selector_dir.mkdir(parents=True, exist_ok=True)
    content_dir.mkdir(parents=True, exist_ok=True)
    js_scripts_dir.mkdir(parents=True, exist_ok=True)

    mocker.patch(
        'yosoi.storage.persistence.init_yosoi',
        side_effect=[selector_dir, content_dir],
    )
    mocker.patch(
        'yosoi.storage.js_scripts.init_yosoi',
        return_value=js_scripts_dir,
    )
    mocker.patch('yosoi.storage.tracking.get_tracking_path', return_value=tmp_path / 'tracking.json')
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value=str(tmp_path / 'test.log'))
    mocker.patch('yosoi.core.discovery.field_agent.create_model')
    mocker.patch('yosoi.core.discovery.field_agent.Agent')
    return selector_dir


def _mock_fetcher(mocker, html: str, url: str = 'https://example.com') -> object:
    fetcher = mocker.AsyncMock()
    fetcher.__aenter__ = mocker.AsyncMock(return_value=fetcher)
    fetcher.__aexit__ = mocker.AsyncMock(return_value=None)
    fetcher.supports_browse = False
    fetcher.fetch = mocker.AsyncMock(
        return_value=FetchResult(
            url=url,
            html=html,
            status_code=200,
            metadata=ContentMetadata(content_length=len(html)),
        )
    )
    mocker.patch('yosoi.core.pipeline.create_fetcher', return_value=fetcher)
    return fetcher


# ---------------------------------------------------------------------------
# Track 4 tests
# ---------------------------------------------------------------------------


async def test_pipeline_fresh_discovery_with_mountainhome_html(mocker, mock_llm_config, tmp_path):
    """Fresh discovery path with real Mountainhome Herald HTML (force=True)."""
    _patch_common(mocker, tmp_path)
    html = load_html(MOUNTAINHOME_HOME)
    _mock_fetcher(mocker, html, url='https://mountainhome.example.com')

    discovered_map = {
        'headline': {'primary': {'strategy': 'css', 'level': 1, 'value': '.pageTitle'}},
        'author': {'primary': {'strategy': 'css', 'level': 1, 'value': '.headerBar'}},
        'date': {'primary': {'strategy': 'css', 'level': 1, 'value': '.footerBar'}},
        'body_text': {'primary': {'strategy': 'css', 'level': 1, 'value': '.navBar'}},
        'related_content': {'primary': {'strategy': 'css', 'level': 1, 'value': '.newsTicker'}},
    }
    mocker.patch(
        'yosoi.core.discovery.orchestrator.DiscoveryOrchestrator.discover_selectors',
        new=mocker.AsyncMock(return_value=discovered_map),
    )

    pipeline = Pipeline(mock_llm_config, contract=NewsArticle)
    await pipeline.process_url('https://mountainhome.example.com', force=True)

    saved = await pipeline.storage.load_selectors('mountainhome.example.com')
    assert saved is not None
    assert 'headline' in saved


async def test_pipeline_multi_item_catalog_extraction(mocker, mock_llm_config, tmp_path):
    """Multi-item extraction from VaultMart catalog using .product-card container."""
    _patch_common(mocker, tmp_path)
    html = load_html(VAULTMART_CATALOG)
    _mock_fetcher(mocker, html, url='https://vaultmart.example.com')

    # Selectors that match the real VaultMart catalog HTML structure
    discovered_map = {
        'name': {'primary': {'strategy': 'css', 'level': 1, 'value': '.product-card-name'}},
        'price': {'primary': {'strategy': 'css', 'level': 1, 'value': '.product-card-price'}},
        'root': '.product-card',
    }
    mocker.patch(
        'yosoi.core.discovery.orchestrator.DiscoveryOrchestrator.discover_selectors',
        new=mocker.AsyncMock(return_value=discovered_map),
    )

    pipeline = Pipeline(mock_llm_config, contract=ProductContract)
    await pipeline.process_url('https://vaultmart.example.com', force=True)

    saved = await pipeline.storage.load_selectors('vaultmart.example.com')
    assert saved is not None
    assert 'name' in saved


async def test_pipeline_cached_selectors_skip_verification(mocker, mock_llm_config, tmp_path):
    """Cached-selector path with skip_verification=True bypasses fetch+verify (lines 830-835)."""
    _patch_common(mocker, tmp_path)
    html = load_html(MOUNTAINHOME_HOME)
    _mock_fetcher(mocker, html, url='https://cache-test.example.com')

    pipeline = Pipeline(mock_llm_config, contract=NewsArticle)

    # Pre-populate the selector cache with snapshots
    snapshots = {
        'headline': _snapshot('.pageTitle'),
        'author': _snapshot('.headerBar'),
        'date': _snapshot('.footerBar'),
        'body_text': _snapshot('.navBar'),
        'related_content': _snapshot('.newsTicker'),
    }
    await pipeline.storage.save_snapshots(
        'https://cache-test.example.com/news',
        snapshots,
    )

    # With skip_verification=True and cached selectors present, pipeline
    # skips the LLM discovery and uses cached selectors directly.
    discovery_mock = mocker.patch(
        'yosoi.core.discovery.orchestrator.DiscoveryOrchestrator.discover_selectors',
        new=mocker.AsyncMock(return_value={}),
    )

    await pipeline.process_url(
        'https://cache-test.example.com/news',
        force=False,
        skip_verification=True,
    )

    # Discovery should not be called — cached path short-circuits it
    discovery_mock.assert_not_called()


async def test_pipeline_cached_selectors_with_fetch_and_verify(mocker, mock_llm_config, tmp_path):
    """Cached path fetches HTML and re-verifies selectors before extraction (lines 785-800)."""
    _patch_common(mocker, tmp_path)
    html = load_html(MOUNTAINHOME_HOME)
    _mock_fetcher(mocker, html, url='https://verify-test.example.com')

    pipeline = Pipeline(mock_llm_config, contract=NewsArticle)

    # Pre-populate snapshot cache
    snapshots = {
        'headline': _snapshot('.pageTitle'),
        'author': _snapshot('.headerBar'),
        'date': _snapshot('.footerBar'),
        'body_text': _snapshot('.navBar'),
        'related_content': _snapshot('.newsTicker'),
    }
    await pipeline.storage.save_snapshots(
        'https://verify-test.example.com/news',
        snapshots,
    )

    # Discovery should not be called when cached selectors are still valid
    discovery_mock = mocker.patch(
        'yosoi.core.discovery.orchestrator.DiscoveryOrchestrator.discover_selectors',
        new=mocker.AsyncMock(return_value={}),
    )

    await pipeline.process_url(
        'https://verify-test.example.com/news',
        force=False,
        skip_verification=False,  # verification path
    )

    # Cached selectors exist and should verify against the fixture HTML
    discovery_mock.assert_not_called()

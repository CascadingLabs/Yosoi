"""Integration test for the recipe pipeline path.

Uses a real Yosoi contract and a real RecipeBundle written to a tempfile, then
verifies that Pipeline accepts the pre-loaded snapshots and skips LLM discovery.

Place this file at:
    tests/integration/test_recipe_integration.py

No live network. No LLM. All disk I/O goes to tmp_path.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone

import pytest

import yosoi as ys
from yosoi.models.contract import Contract
from yosoi.models.recipe import RecipeBundle
from yosoi.models.results import ContentMetadata, FetchResult
from yosoi.models.snapshot import SelectorSnapshot, SnapshotMap, SnapshotStatus
from yosoi.storage.recipe_loader import load_recipe

# ---------------------------------------------------------------------------
# Contract under test
# ---------------------------------------------------------------------------


class Product(Contract):
    """A product card in an e-shop catalog."""

    name: str = ys.Title(description='Product name')
    price: float = ys.Price(description='Product price as a number')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc)


def _snapshot(css: str) -> SelectorSnapshot:
    return SelectorSnapshot(
        primary={'type': 'css', 'value': css},
        discovered_at=_NOW,
        status=SnapshotStatus.ACTIVE,
    )


def _make_bundle(url: str = 'https://qscrape.dev/l1/eshop/catalog/') -> tuple[RecipeBundle, str]:
    """Build a RecipeBundle with fake-but-valid snapshots and save to a tempfile."""
    domain = 'qscrape.dev'
    snap_map = SnapshotMap(
        url=url,
        domain=domain,
        snapshots={
            'name': _snapshot('h1.product-name'),
            'price': _snapshot('.price'),
        },
    )
    bundle = RecipeBundle.from_parts(Product, {domain: snap_map})

    fd, path = tempfile.mkstemp(suffix='.json')
    os.close(fd)
    bundle.save(path)
    return bundle, path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_load_recipe_returns_valid_bundle():
    """load_recipe round-trips the bundle from a local file."""
    _bundle, path = _make_bundle()
    try:
        loaded = await load_recipe(path)
        assert loaded.contract.name == 'Product'
        assert 'qscrape.dev' in loaded.selectors
    finally:
        os.unlink(path)


async def test_bundle_snapshots_accessible_after_load():
    """Snapshot data survives the save/load cycle."""
    _bundle, path = _make_bundle()
    try:
        loaded = await load_recipe(path)
        snap_map = loaded.snapshots_for_domain('qscrape.dev')
        assert snap_map is not None
        assert 'name' in snap_map.snapshots
        assert 'price' in snap_map.snapshots
    finally:
        os.unlink(path)


async def test_pipeline_uses_preloaded_snapshots_and_skips_discovery(mocker, tmp_path):
    """Pipeline with preloaded_snapshots skips LLM discovery for that domain."""
    from yosoi.core.pipeline import Pipeline

    # Patch all heavy setup so Pipeline.__init__ doesn't hit disk/network.
    selector_dir = tmp_path / 'selectors'
    content_dir = tmp_path / 'content'
    selector_dir.mkdir()
    content_dir.mkdir()
    mocker.patch('yosoi.storage.persistence.init_yosoi', side_effect=[selector_dir, content_dir])
    mocker.patch('yosoi.storage.tracking.get_tracking_path', return_value=tmp_path / 'tracking.json')
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value=str(tmp_path / 'test.log'))
    mocker.patch('yosoi.core.discovery.field_agent.create_model')
    mocker.patch('yosoi.core.discovery.field_agent.Agent')

    # Build a bundle and extract its snapshots.
    bundle, path = _make_bundle()
    os.unlink(path)
    snap_map = bundle.selectors['qscrape.dev']

    # Wire pre-loaded snapshots into the pipeline.
    pipeline = Pipeline(
        llm_config='groq:llama-3.3-70b-versatile',
        contract=Product,
        preloaded_snapshots={'qscrape.dev': snap_map},
        quiet=True,
    )

    # storage should report the domain as having cached selectors.
    assert pipeline.storage.has_preloaded()
    snapshots = await pipeline.storage.load_snapshots('qscrape.dev')
    assert snapshots is not None
    assert 'name' in snapshots
    assert 'price' in snapshots


async def test_pipeline_preloaded_skips_discovery_call(mocker, tmp_path):
    """LLM discovery is never invoked when snapshots are pre-loaded and valid."""
    from yosoi.core.pipeline import Pipeline

    selector_dir = tmp_path / 'selectors'
    content_dir = tmp_path / 'content'
    selector_dir.mkdir()
    content_dir.mkdir()
    mocker.patch('yosoi.storage.persistence.init_yosoi', side_effect=[selector_dir, content_dir])
    mocker.patch('yosoi.storage.tracking.get_tracking_path', return_value=tmp_path / 'tracking.json')
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value=str(tmp_path / 'test.log'))
    mocker.patch('yosoi.core.discovery.field_agent.create_model')
    mocker.patch('yosoi.core.discovery.field_agent.Agent')

    bundle, path = _make_bundle()
    os.unlink(path)
    snap_map = bundle.selectors['qscrape.dev']

    # Spy on discover_selectors to confirm it is never called.
    discovery_mock = mocker.patch(
        'yosoi.core.discovery.orchestrator.DiscoveryOrchestrator.discover_selectors',
        new=mocker.AsyncMock(return_value={}),
    )

    mock_fetcher = mocker.AsyncMock()
    mock_fetcher.fetch = mocker.AsyncMock(
        return_value=FetchResult(
            url='https://qscrape.dev/l1/eshop/catalog/',
            html='<html><body><h1>Product</h1></body></html>',
            status_code=200,
            metadata=ContentMetadata(content_length=100),
        )
    )
    mocker.patch('yosoi.core.pipeline.base.create_fetcher', return_value=mock_fetcher)

    pipeline = Pipeline(
        llm_config='groq:llama-3.3-70b-versatile',
        contract=Product,
        preloaded_snapshots={'qscrape.dev': snap_map},
        quiet=True,
    )

    # Override process_url to just check the cache path directly.
    await pipeline.process_url(
        'https://qscrape.dev/l1/eshop/catalog/',
        force=False,
        skip_verification=True,
    )

    discovery_mock.assert_not_called()


async def test_recipe_bundle_integrity_check_on_load(tmp_path):
    """A tampered recipe file fails integrity check when loaded via load_recipe."""
    import json

    _bundle, path = _make_bundle()

    with open(path) as f:
        raw = json.load(f)
    raw['contract']['name'] = 'Injected'
    with open(path, 'w') as f:
        json.dump(raw, f)

    try:
        with pytest.raises(ValueError, match='integrity'):
            await load_recipe(path)
    finally:
        os.unlink(path)


async def test_subdomain_fallback_in_preloaded_storage(mocker, tmp_path):
    """www.qscrape.dev finds snapshots keyed under qscrape.dev via subdomain fallback."""
    from yosoi.core.pipeline import Pipeline

    selector_dir = tmp_path / 'selectors'
    content_dir = tmp_path / 'content'
    selector_dir.mkdir()
    content_dir.mkdir()
    mocker.patch('yosoi.storage.persistence.init_yosoi', side_effect=[selector_dir, content_dir])
    mocker.patch('yosoi.storage.tracking.get_tracking_path', return_value=tmp_path / 'tracking.json')
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value=str(tmp_path / 'test.log'))
    mocker.patch('yosoi.core.discovery.field_agent.create_model')
    mocker.patch('yosoi.core.discovery.field_agent.Agent')

    bundle, path = _make_bundle()
    os.unlink(path)
    snap_map = bundle.selectors['qscrape.dev']

    pipeline = Pipeline(
        llm_config='groq:llama-3.3-70b-versatile',
        contract=Product,
        preloaded_snapshots={'qscrape.dev': snap_map},
        quiet=True,
    )

    # Subdomain should resolve via the fallback logic in _preloaded_for_domain.
    result = await pipeline.storage.load_snapshots('www.qscrape.dev')
    assert result is not None
    assert 'name' in result

"""Offline pipeline tests for the flag-gated reuse-hint (CAS-85).

No LLM, no network. We seed the selector cache with snapshots we *know* are
true for a fixture, write the matching seed observation, then drive the real
``_try_cached`` path on a same-domain replay page and assert what the hint does:

  * a same-class replay (catalog → catalog) is TRY_REUSE → the cached path runs
    and LLM discovery is never called;
  * a different-class replay (catalog seed → product detail page) is REDISCOVER → the hint
    skips the cached replay, so the pipeline falls through to fresh discovery
    (discovery IS called) — this is the only behavior the flag actually changes;
  * with the flag OFF the same different-class replay does NOT skip — proving the
    toggle is inert by default.

This is the cheap, free-to-iterate harness: tune the recommender thresholds and
re-run, no model in the loop. The hot-path LLM run is a later sanity check.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from tests.fixtures import VAULTMART_CATALOG, VAULTMART_PRODUCT, load_html
from tests.integration.test_pipeline_fixtures import (
    ProductContract,
    _mock_fetcher,
    _patch_common,
    _snapshot,
)
from yosoi.core.pipeline import Pipeline
from yosoi.generalization.capture import observe_html
from yosoi.generalization.seeds import save_seed
from yosoi.generalization.store import DecisionStore

_DOMAIN = 'https://vaultmart.example.com'
_SEED_URL = f'{_DOMAIN}/catalog'
_CATALOG_REPLAY_URL = f'{_DOMAIN}/catalog/page/2'
_PDP_REPLAY_URL = f'{_DOMAIN}/product/VM-MIN-001'
_ROOT_SELECTOR = '.product-card'

# The cached recipe we *know* is true for the VaultMart catalog fixture.
_CATALOG_SNAPSHOTS = {
    'name': _snapshot('.product-card-name'),
    'price': _snapshot('.product-card-price'),
    'root': _snapshot(_ROOT_SELECTOR),
}


@pytest.fixture
def isolated_generalization(tmp_path: Path, mocker: MockerFixture) -> Path:
    """Route the seed store and decision ledger to an isolated tmp dir."""
    home = tmp_path / 'generalization'
    home.mkdir()
    mocker.patch('yosoi.generalization.seeds.init_yosoi', return_value=home)
    mocker.patch('yosoi.generalization.store.init_yosoi', return_value=home)
    return home


async def _seed_catalog(pipeline: Pipeline) -> None:
    """Pre-populate the cache + seed observation from the catalog fixture."""
    await pipeline.storage.save_snapshots(_SEED_URL, _CATALOG_SNAPSHOTS)
    save_seed(observe_html(_SEED_URL, load_html(VAULTMART_CATALOG), row_selector=_ROOT_SELECTOR))


def _discovery_spy(mocker: MockerFixture):
    """Patch fresh discovery to a no-LLM stub and return the spy.

    Returns selectors that match the PDP fixture (the only page the REDISCOVER
    path actually re-discovers on), so the fresh path completes instead of
    raising on verify. The TRY_REUSE / flag-off tests never call discovery, so
    the return value is irrelevant there.
    """
    return mocker.patch(
        'yosoi.core.discovery.orchestrator.DiscoveryOrchestrator.discover_selectors',
        new=mocker.AsyncMock(
            return_value={
                'name': {'primary': {'strategy': 'css', 'level': 1, 'value': '.productDetail-name'}},
                'price': {'primary': {'strategy': 'css', 'level': 1, 'value': '.productDetail-price'}},
            }
        ),
    )


async def test_same_class_replay_reuses_cache_without_discovery(
    mocker, mock_llm_config, tmp_path, isolated_generalization, monkeypatch
):
    """Catalog→catalog replay is TRY_REUSE: cached path runs, no LLM discovery."""
    monkeypatch.setenv('YOSOI_REUSE_HINT', '1')
    monkeypatch.setenv('YOSOI_REUSE_PROFILE', 'balanced')
    _patch_common(mocker, tmp_path)
    _mock_fetcher(mocker, load_html(VAULTMART_CATALOG), url=_CATALOG_REPLAY_URL)
    discovery = _discovery_spy(mocker)

    pipeline = Pipeline(mock_llm_config, contract=ProductContract)
    await _seed_catalog(pipeline)
    await pipeline.process_url(_CATALOG_REPLAY_URL, force=False)

    discovery.assert_not_called()
    # The advisory decision was logged to the flywheel ledger.
    assert sorted(isolated_generalization.glob('*.jsonl'))


async def test_wrong_class_replay_skips_cache_and_rediscovers(
    mocker, mock_llm_config, tmp_path, isolated_generalization, monkeypatch
):
    """Catalog-seed → product-detail replay is REDISCOVER: the hint skips the
    cached replay, so the pipeline falls through to fresh discovery (the win)."""
    monkeypatch.setenv('YOSOI_REUSE_HINT', '1')
    monkeypatch.setenv('YOSOI_REUSE_PROFILE', 'balanced')  # balanced acts on REFUSE
    _patch_common(mocker, tmp_path)
    _mock_fetcher(mocker, load_html(VAULTMART_PRODUCT), url=_PDP_REPLAY_URL)
    discovery = _discovery_spy(mocker)

    pipeline = Pipeline(mock_llm_config, contract=ProductContract)
    await _seed_catalog(pipeline)
    await pipeline.process_url(_PDP_REPLAY_URL, force=False)

    discovery.assert_called()  # cached replay was skipped → fresh discovery ran


async def test_strict_profile_observes_without_acting(
    mocker, mock_llm_config, tmp_path, isolated_generalization, monkeypatch
):
    """Strict profile (default): a matching catalog→catalog replay is recorded and
    quarantined for review, but the hint changes no behavior — the cached path runs
    (no discovery) and the decision lands in the pending-review queue."""
    monkeypatch.setenv('YOSOI_REUSE_HINT', '1')
    monkeypatch.setenv('YOSOI_REUSE_PROFILE', 'strict')
    _patch_common(mocker, tmp_path)
    _mock_fetcher(mocker, load_html(VAULTMART_CATALOG), url=_CATALOG_REPLAY_URL)
    discovery = _discovery_spy(mocker)

    pipeline = Pipeline(mock_llm_config, contract=ProductContract)
    await _seed_catalog(pipeline)
    await pipeline.process_url(_CATALOG_REPLAY_URL, force=False)

    discovery.assert_not_called()  # behavior unchanged
    assert len(DecisionStore().pending()) == 1  # but it was queued for review


async def test_flag_off_is_inert(mocker, mock_llm_config, tmp_path, isolated_generalization, monkeypatch):
    """Flag off: the hint never runs — same cached behavior as before, and no
    ledger row. Contrast with the flag-on catalog→catalog test, which takes the
    identical cached path but DOES log a decision: the only difference the toggle
    makes on a matching page is the flywheel write."""
    monkeypatch.delenv('YOSOI_REUSE_HINT', raising=False)
    _patch_common(mocker, tmp_path)
    _mock_fetcher(mocker, load_html(VAULTMART_CATALOG), url=_CATALOG_REPLAY_URL)
    discovery = _discovery_spy(mocker)

    pipeline = Pipeline(mock_llm_config, contract=ProductContract)
    await _seed_catalog(pipeline)
    await pipeline.process_url(_CATALOG_REPLAY_URL, force=False)

    discovery.assert_not_called()
    assert not sorted(isolated_generalization.glob('*.jsonl'))  # nothing logged when off

"""Opt-in live dogfood for the experimental rendered-DOM pruner.

The frozen TodoMVC episode under `tests/boss_fights/dom/todomvc_live/` gates CI. This
captures the same app through a real VoidCrawl browser *now* and asserts the invariants
that must hold for any capture, so drift in the app shows up as a smoke failure rather
than as silence behind pinned bytes.

Nothing here writes into `tests/`: the frozen artifacts stay byte-exact.
"""

from __future__ import annotations

import os

import pytest
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from scripts.capture_dom_todomvc import CAPTURE_JS, URL, _snapshot
from tests.smoke._observations import resolution_failure
from yosoi.observations.artifacts.memory import MemoryArtifactStore
from yosoi.observations.index.compiler import ObservationIndexCompiler
from yosoi.observations.index.inspect import InspectionBudget, ObservationInspector
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.snapshot import CaptureProfile, ObservationSnapshot
from yosoi.observations.pruning.dom import DomPruner
from yosoi.observations.pruning.protocol import PruningInput, PruningPolicy

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(
        os.getenv('YOSOI_LIVE_SMOKE') != '1',
        reason='set YOSOI_LIVE_SMOKE=1 to run live DOM-pruning smoke tests',
    ),
]

SNAPSHOT_ID = 'live-dom-smoke'
TODOS = ('Buy milk', 'Read design', 'Ship beta')


@pytest.fixture(scope='module')
def live_dom() -> bytes:
    """Drive a real browser to a known TodoMVC state and capture its rendered DOM.

    Retried because the target is the public internet: a DNS blip or a slow navigation is
    noise about the network, not a finding about the pruner. A site that is genuinely down
    still fails, just after the retries are spent.
    """
    import asyncio

    from voidcrawl import BrowserPool, PoolConfig
    from voidcrawl._ext import NavigationError

    async def capture() -> bytes:
        async with BrowserPool(PoolConfig()) as pool, pool.acquire() as tab:
            await tab.goto(URL, capture_endpoints=True)
            await tab.evaluate_js('localStorage.clear(); sessionStorage.clear();')
            await tab.goto(URL, capture_endpoints=True)
            for title in TODOS:
                await tab.type_into('.new-todo', title)
                await tab.evaluate_js(
                    "document.querySelector('.new-todo').dispatchEvent(new Event('change', {bubbles: true}))"
                )
            return _snapshot(await tab.evaluate_js(CAPTURE_JS), SNAPSHOT_ID)

    for attempt in Retrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=10),
        retry=retry_if_exception_type(NavigationError),
        reraise=True,
    ):
        with attempt:
            return asyncio.run(capture())
    raise AssertionError('unreachable: Retrying with reraise=True either returns or raises')


@pytest.fixture(scope='module')
def live_dom_index(live_dom: bytes):
    """Prune and compile the live DOM snapshot into a walkable index."""
    store = MemoryArtifactStore()
    artifact = store.put(
        snapshot_id=SNAPSHOT_ID,
        kind=EvidenceKind.RENDERED_DOM,
        media_type='application/json',
        data=live_dom,
    )
    snapshot = ObservationSnapshot(
        run_id=SNAPSHOT_ID,
        episode_id=SNAPSHOT_ID,
        snapshot_id=SNAPSHOT_ID,
        requested_profile=CaptureProfile.BROWSER_HEADLESS,
        artifacts=(artifact,),
    )
    view = DomPruner().prune(PruningInput(source=artifact, data=live_dom), PruningPolicy())
    index = ObservationIndexCompiler().compile(snapshot, (view,))
    return index, ObservationInspector(store, snapshot), view


def test_live_dom_index_is_substantially_smaller(live_dom: bytes, live_dom_index) -> None:
    _, _, view = live_dom_index
    assert len(live_dom) / view.stats.output_bytes >= 3


def test_live_todo_list_collapses_and_names_its_members(live_dom_index) -> None:
    """The typed-in todos must be visible IN the index, not only after an expand."""
    index, _, _ = live_dom_index
    regions = [entry for entry in index.entries if entry.coverage is not None]

    assert regions, 'three sibling todos must collapse into a region'
    todo_region = next(entry for entry in regions if entry.coverage.observed == len(TODOS))
    for title in TODOS:
        assert f'"{title}"' in todo_region.summary


def test_live_todo_members_are_keyed_not_positional(live_dom_index) -> None:
    """TodoMVC gives each row a data-id, so members must be addressed durably."""
    index, inspector, _ = live_dom_index
    todo_region = next(
        entry for entry in index.entries if entry.coverage is not None and entry.coverage.observed == len(TODOS)
    )

    page = inspector.expand(todo_region.ref, InspectionBudget())

    assert len(page.members) == len(TODOS)
    assert all(member.stable for member in page.members), 'members must not be addressed by position'


def test_every_live_dom_address_resolves(live_dom_index) -> None:
    """No entry in the index may be a dead pointer into the snapshot."""
    index, inspector, _ = live_dom_index

    unresolved = [note for entry in index.entries if (note := resolution_failure(inspector, entry))]

    assert not unresolved, f'DOM index addresses that did not resolve: {unresolved}'

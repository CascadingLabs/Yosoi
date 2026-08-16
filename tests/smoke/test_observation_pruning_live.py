"""Opt-in live dogfood for the observation pruners.

The boss fights gate CI against frozen artifacts, deliberately: pinned bytes are the only
way to assert a digest or an exact member count. That leaves one thing unproven — whether
the pruners still hold up against a page as it is served *today*. These tests close that
gap and never gate: they assert the invariants that must survive any capture (the index is
an order of magnitude smaller, a repeated run costs one region, every member stays
reachable) rather than counts that legitimately drift when a site is edited.
"""

from __future__ import annotations

import os
import urllib.request
from urllib.error import URLError

import pytest
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from tests.smoke._observations import resolution_failure
from yosoi.observations.artifacts.memory import MemoryArtifactStore
from yosoi.observations.index.compiler import ObservationIndexCompiler
from yosoi.observations.index.inspect import InspectionBudget, ObservationInspector
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.index import ObservationIndex
from yosoi.observations.models.snapshot import CaptureProfile, ObservationSnapshot
from yosoi.observations.pruning.html import BodyPruner, DeclarationPruner
from yosoi.observations.pruning.protocol import PruningInput, PruningPolicy

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(
        os.getenv('YOSOI_LIVE_SMOKE') != '1',
        reason='set YOSOI_LIVE_SMOKE=1 to run live observation-pruning smoke tests',
    ),
]

LIVE_URL = 'http://books.toscrape.com/'
SNAPSHOT_ID = 'live-html-smoke'


@pytest.fixture(scope='module')
def live_page() -> bytes:
    """Fetch the dogfood page once per module, over the real network.

    Retried because the target is the public internet: a DNS blip or a slow response is
    noise about the network, not a finding about the pruner. A site that is genuinely down
    still fails, just after the retries are spent.
    """
    request = urllib.request.Request(LIVE_URL, headers={'User-Agent': 'yosoi-live-smoke/1'})
    for attempt in Retrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=10),
        retry=retry_if_exception_type((URLError, TimeoutError)),
        reraise=True,
    ):
        with attempt, urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    raise AssertionError('unreachable: Retrying with reraise=True either returns or raises')


@pytest.fixture(scope='module')
def live_index(live_page: bytes) -> tuple[ObservationIndex, ObservationInspector, int, int]:
    """Prune and compile the live bytes into a walkable index."""
    store = MemoryArtifactStore()
    artifact = store.put(
        snapshot_id=SNAPSHOT_ID,
        kind=EvidenceKind.SOURCE_HTML,
        media_type='text/html',
        data=live_page,
    )
    snapshot = ObservationSnapshot(
        run_id=SNAPSHOT_ID,
        episode_id=SNAPSHOT_ID,
        snapshot_id=SNAPSHOT_ID,
        requested_profile=CaptureProfile.HTTP_STATIC,
        artifacts=(artifact,),
    )
    source = PruningInput(source=artifact, data=live_page)
    policy = PruningPolicy()
    views = (DeclarationPruner().prune(source, policy), BodyPruner().prune(source, policy))
    index = ObservationIndexCompiler().compile(snapshot, views)
    output_bytes = sum(view.stats.output_bytes for view in views)
    return index, ObservationInspector(store, snapshot), len(live_page), output_bytes


def test_live_index_is_an_order_of_magnitude_smaller(live_index) -> None:
    index, _, source_bytes, output_bytes = live_index
    assert index.entries, 'a live page must produce a non-empty index'
    assert source_bytes / output_bytes >= 10


def test_live_repeated_records_collapse_into_regions(live_index) -> None:
    """The product grid is a repeated run; it must cost regions, not one entry per record."""
    index, _, _, _ = live_index
    regions = [entry for entry in index.entries if entry.coverage is not None]

    assert regions, 'a catalogue page with repeated records must produce at least one region'
    biggest = max(regions, key=lambda entry: entry.coverage.observed)
    assert biggest.coverage.observed >= 10
    # Collapsing is only honest if it also says what it collapsed.
    assert '"' in (biggest.summary or ''), 'a region must sample its members, not just count them'


def test_every_live_region_member_stays_reachable(live_index) -> None:
    """Collapsing must not cost reachability: members page out through `expand`."""
    index, inspector, _, _ = live_index
    regions = [entry for entry in index.entries if entry.coverage is not None]
    biggest = max(regions, key=lambda entry: entry.coverage.observed)

    page = inspector.expand(biggest.ref, InspectionBudget(max_items=5))

    assert page.members
    assert len(page.members) <= 5
    for member in page.members:
        detail = inspector.inspect(member.ref, InspectionBudget()).content
        assert detail, 'every addressed member must resolve back to bytes'


def test_every_live_index_address_resolves(live_index) -> None:
    """The core promise: nothing in the index is a dead pointer.

    An index entry exists to be inspected. One that names something the resolver cannot find
    is worse than an omission, because the reader has no way to tell the difference until
    they spend the hop.
    """
    index, inspector, _, _ = live_index

    unresolved = [note for entry in index.entries if (note := resolution_failure(inspector, entry))]

    assert not unresolved, f'index addresses that did not resolve against the live page: {unresolved}'

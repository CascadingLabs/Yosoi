"""10,000 rows: the scale the body reducer exists for, measured instead of asserted.

Everything else in this tier argues repeat collapse from 20 product cards. That proves the
rule fires; it does not prove the rule *pays*, and it cannot catch a quadratic in key
assignment or signature caching — both of which are only visible at four digits of rows.

The artifact is generated, not frozen: 1.7 MB is not committable. Bytes are pinned by digest
in the manifest, so "generated" does not mean "unpinned".
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.boss_fights.conftest import HtmlWorkload
from tests.boss_fights.generators import render_repeat_table
from yosoi.observations.index.inspect import InspectionBudget

WORKLOAD = Path(__file__).parent

_PAGE = 2_500
"""Members per `expand` call in the full sweep. Four pages, so four parses, not twenty."""


@pytest.fixture(scope='module')
def ledger(generated_html_workload: Callable[[Path, bytes], HtmlWorkload]) -> HtmlWorkload:
    """Assemble the 10,000-row workload once per module."""
    return generated_html_workload(WORKLOAD, render_repeat_table(_manifest()['rows']))


@pytest.fixture(scope='module')
def control(generated_html_workload: Callable[[Path, bytes], HtmlWorkload]) -> HtmlWorkload:
    """Assemble the 1,000-row scaling control from the same generator."""
    return generated_html_workload(WORKLOAD, render_repeat_table(_manifest()['control_rows']))


def _manifest() -> dict:
    """Read the manifest without assembling a workload, to learn the row counts."""
    import tomllib

    return tomllib.loads((WORKLOAD / 'manifest.toml').read_text())


def _region(workload: HtmlWorkload) -> int:
    """Return the index ordinal of the row region named by ground truth."""
    oracle = workload.ground_truth['required_region'][0]['oracle_xpath']
    reaching = workload.entries_reaching(oracle)
    assert reaching, 'the row region is unreachable from the index'
    assert len(reaching) == 1, f'{len(reaching)} entries claim the row region; it must cost exactly one'
    return reaching[0]


def test_generated_artifacts_match_their_pinned_digests(ledger: HtmlWorkload, control: HtmlWorkload) -> None:
    """A generated artifact is still pinned: the generator is part of the gate."""
    manifest = ledger.manifest

    assert hashlib.sha256(ledger.data).hexdigest() == manifest['generated_sha256']
    assert len(ledger.data) == manifest['generated_bytes']
    assert hashlib.sha256(control.data).hexdigest() == manifest['control_generated_sha256']


def test_ten_thousand_rows_cost_one_region_and_one_exemplar(ledger: HtmlWorkload) -> None:
    """The headline claim, at the scale it is made for."""
    expected = ledger.ground_truth['required_region'][0]
    region = ledger.index.entries[_region(ledger)]

    assert region.coverage is not None
    assert region.coverage.observed == expected['expected_members'] == 10_000
    assert region.coverage.complete, 'static HTML holds every member it has'
    # The region entry is followed immediately by its exemplar, and by nothing else per row.
    exemplar = ledger.index.entries[region.ordinal + 1]
    assert 'exemplar of ×10000' in exemplar.summary


def test_index_size_does_not_depend_on_row_count(ledger: HtmlWorkload, control: HtmlWorkload) -> None:
    """10x the rows must buy 0 extra entries — that is what collapse means."""
    assert len(ledger.index.entries) == len(control.index.entries)

    total = sum(view.stats.output_bytes for view in ledger.views)
    assert total <= ledger.manifest['budget_output_bytes']
    # And the 1.7 MB document reduces by three orders of magnitude, not one.
    assert len(ledger.data) / total >= 500


def test_unique_evidence_survives_a_document_dominated_by_repetition(ledger: HtmlWorkload) -> None:
    """Volume must not crowd out the one-off declarations and prose around it."""
    unreachable = []
    for evidence in ledger.ground_truth['required_evidence']:
        ordinals = ledger.entries_reaching(evidence['oracle_xpath'])
        if not ordinals:
            unreachable.append(evidence['id'])
            continue
        detail = ledger.inspect_bytes(ordinals[0]).decode(errors='replace')
        expected = evidence.get('oracle_contains')
        if expected and expected.lower() not in detail.lower():
            unreachable.append(f'{evidence["id"]} (address resolved, evidence absent)')
    assert not unreachable, f'evidence unreachable from the index: {unreachable}'


def test_every_row_is_reachable_and_durably_addressed(ledger: HtmlWorkload) -> None:
    """All 10,000 members, swept in pages: no gaps, no duplicates, no positional fallbacks."""
    region_ordinal = _region(ledger)
    seen: dict[int, str] = {}
    offset = 0
    while True:
        page = ledger.expand(region_ordinal, InspectionBudget(max_items=_PAGE), offset=offset)
        for member in page.members:
            assert member.ordinal not in seen, f'member {member.ordinal} returned twice'
            assert member.stable, f'member {member.ordinal} is addressable only by position'
            seen[member.ordinal] = member.ref.locator
        if not page.truncated:
            break
        offset += len(page.members)

    assert sorted(seen) == list(range(10_000))
    assert len(set(seen.values())) == 10_000, 'two members share one address'
    # And the LAST member's address resolves back to that exact row, not to its neighbour.
    detail = ledger.inspector.inspect(
        ledger.expand(region_ordinal, InspectionBudget(max_items=1), offset=9_999).members[0].ref,
        InspectionBudget(),
    ).content.decode(errors='replace')
    assert 'Record 010000' in detail


def test_expansion_stays_bounded_at_scale(ledger: HtmlWorkload) -> None:
    """A collapsed 10,000-member region must never hand back 10,000 members at once."""
    region_ordinal = _region(ledger)

    first = ledger.expand(region_ordinal, InspectionBudget(max_items=50))
    later = ledger.expand(region_ordinal, InspectionBudget(max_items=50), offset=5_000)

    assert len(first.members) == 50
    assert first.truncated
    assert [member.ordinal for member in later.members] == list(range(5_000, 5_050))
    assert {member.ref for member in first.members}.isdisjoint({member.ref for member in later.members})


def test_reduction_is_byte_identical_across_runs(
    generated_html_workload: Callable[[Path, bytes], HtmlWorkload], ledger: HtmlWorkload
) -> None:
    """Same bytes, same pruner version, same policy hash — same output, at scale too."""
    again = generated_html_workload(WORKLOAD, render_repeat_table(ledger.manifest['rows']))

    assert [(entry.ref, entry.label, entry.summary) for entry in again.index.entries] == [
        (entry.ref, entry.label, entry.summary) for entry in ledger.index.entries
    ]


def test_cost_grows_linearly_not_quadratically(
    generated_html_workload: Callable[[Path, bytes], HtmlWorkload], ledger: HtmlWorkload
) -> None:
    """Cost must track row count, not its square.

    10x the rows costs at least 10x the time when the reduction is linear; a quadratic term —
    the per-element key-uniqueness formulation this package explicitly rejected, or a
    signature cache that misses — costs ~100x. The gate sits between them, as a ratio against
    the 1,000-row control rather than an absolute wall clock, so it describes the algorithm
    instead of the machine it ran on.
    """
    manifest = ledger.manifest
    small = render_repeat_table(manifest['control_rows'])
    large = render_repeat_table(manifest['rows'])

    def elapsed(data: bytes) -> float:
        start = time.perf_counter()
        generated_html_workload(WORKLOAD, data)
        return time.perf_counter() - start

    # One warm run each so neither measurement pays for a cold import.
    elapsed(small)
    elapsed(large)
    baseline = min(elapsed(small) for _ in range(3))
    at_scale = min(elapsed(large) for _ in range(3))

    rows_factor = manifest['rows'] / manifest['control_rows']
    assert baseline > 0
    assert at_scale / baseline <= manifest['max_scaling_factor'], (
        f'{rows_factor:.0f}x rows cost {at_scale / baseline:.1f}x time '
        f'({baseline:.3f}s → {at_scale:.3f}s); the reduction is super-linear in row count'
    )

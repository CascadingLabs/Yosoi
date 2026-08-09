"""Reference stability: does an identity still name the same thing in the next capture?

Everything else in this tier tests one snapshot, where a locator is stable by assumption. This
workload captures the same page seven ways — unchanged, and under six deliberate edits — and
asks which identities survive. A `RegionRef` cannot participate: two of its four fields are the
snapshot id and the artifact digest, so it is unequal across captures by construction. `ref_id`
is the value under test.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.boss_fights.conftest import HtmlWorkload
from tests.boss_fights.generators import MUTATIONS, render_mutable_page
from yosoi.observations.index.addressing import parse_address
from yosoi.observations.index.inspect import InspectionBudget

WORKLOAD = Path(__file__).parent


@pytest.fixture(scope='module')
def pages(generated_html_workload: Callable[..., HtmlWorkload]) -> dict[str, HtmlWorkload]:
    """Assemble every mutation of the ledger page once per module."""
    return {name: generated_html_workload(WORKLOAD, render_mutable_page(name)) for name in MUTATIONS}


def _identities(workload: HtmlWorkload) -> set[str]:
    """Return every identity this snapshot minted."""
    return {entry.ref_id for entry in workload.index.entries if entry.ref_id is not None}


def _identity_of(workload: HtmlWorkload, oracle_xpath: str) -> str:
    """Return the identity of the entry that reaches one oracle element."""
    ordinals = workload.entries_reaching(oracle_xpath)
    assert ordinals, f'{oracle_xpath} is unreachable from the index'
    ref_id = workload.index.entries[ordinals[0]].ref_id
    assert ref_id is not None, f'{oracle_xpath} resolved to an entry with no identity'
    return ref_id


def _mutation(workload: HtmlWorkload, name: str) -> dict:
    """Return the ground-truth expectations for one mutation."""
    return next(entry for entry in workload.ground_truth['mutation'] if entry['id'] == name)


def test_the_same_page_captured_twice_yields_the_same_identities(
    generated_html_workload: Callable[..., HtmlWorkload], pages: dict[str, HtmlWorkload]
) -> None:
    """The whole premise: identity comes from the page, not from the capture."""
    again = generated_html_workload(WORKLOAD, render_mutable_page('base'), snapshot_id='second-capture')
    base = pages['base']

    assert _identities(again) == _identities(base)
    assert _identities(base), 'a page with ids, data hooks, and a keyed table must mint identities'
    # And the refs themselves are NOT comparable — that is why identity had to be derived.
    assert {entry.ref for entry in again.index.entries} != {entry.ref for entry in base.index.entries}


def test_an_insert_above_everything_loses_no_references(pages: dict[str, HtmlWorkload]) -> None:
    """Anchoring exists for this case, so it gets its own test rather than a table row."""
    base = _identities(pages['base'])
    after = _identities(pages['section_above'])

    lost = base - after
    assert not lost, f'{len(lost)} of {len(base)} identities did not survive an insert near the top of <body>'


@pytest.mark.parametrize('mutation', [name for name in MUTATIONS if name != 'base'])
def test_identities_survive_exactly_the_mutations_they_should(pages: dict[str, HtmlWorkload], mutation: str) -> None:
    """Each edit is expected to preserve some identities and change others, by name."""
    base, mutant = pages['base'], pages[mutation]
    expectations = _mutation(base, mutation)
    surviving = _identities(mutant)

    if expectations['all_base_ids_preserved']:
        assert not _identities(base) - surviving, 'this edit must not cost a single identity'
    else:
        assert _identities(base) - surviving, 'ground truth expects churn from this edit but none happened'

    for oracle in expectations['must_survive']:
        assert _identity_of(base, oracle) in surviving, f'{oracle} lost its identity to {mutation}'
    for oracle in expectations['must_change']:
        assert _identity_of(base, oracle) not in surviving, f'{oracle} kept an identity {mutation} invalidated'


def test_an_unanchorable_element_is_reachable_but_has_no_identity(pages: dict[str, HtmlWorkload]) -> None:
    """Refusal, not a weaker id: the page offered nothing durable, so nothing is claimed."""
    base = pages['base']
    for expected in base.ground_truth['unanchorable']:
        ordinals = base.entries_reaching(expected['oracle_xpath'])
        assert ordinals, f'{expected["oracle_xpath"]} must still be addressable and inspectable'
        entry = base.index.entries[ordinals[0]]
        assert entry.ref_id is None, 'an address the page cannot anchor must not be handed an identity'
        # Still exact within its own snapshot: refusing identity never costs resolution.
        assert base.inspect_bytes(entry.ordinal, InspectionBudget()), 'the entry must still resolve to bytes'


def test_identity_requires_anchored_stable_and_positional_free(pages: dict[str, HtmlWorkload]) -> None:
    """The three properties are conjunctive, and each one is load-bearing somewhere on this page."""
    entries = pages['base'].index.entries
    addresses = {entry.ordinal: parse_address(entry.ref.locator) for entry in entries}

    for entry in entries:
        address = addresses[entry.ordinal]
        earned = address.is_anchored and address.is_stable and address.is_positional_free
        assert (entry.ref_id is not None) == earned, f'entry {entry.ordinal} disagrees with its own address'

    # And the page really does exercise the refusal path, or the assertion above is vacuous.
    assert any(not addresses[entry.ordinal].is_positional_free for entry in entries)
    assert any(entry.ref_id is None for entry in entries)


def test_identities_are_unique_within_a_snapshot(pages: dict[str, HtmlWorkload]) -> None:
    """Two different things sharing one identity would make a diff silently wrong."""
    for name, workload in pages.items():
        minted = [entry.ref_id for entry in workload.index.entries if entry.ref_id is not None]
        assert len(minted) == len(set(minted)), f'{name} minted a duplicate identity'


@pytest.mark.boss_fight
def test_diff_over_the_mutation_corpus_matches_the_measured_identity_table(
    generated_html_workload: Callable[..., HtmlWorkload],
) -> None:
    """The diff must report exactly what the identity tier already promised for each edit.

    This is a cross-check, not a new claim: `ref_id` survival per mutation was measured when
    anchoring landed, and a diff keyed on those ids must agree with it. Where the two disagree,
    one of them is wrong — and a diff that quietly disagrees is the more dangerous of the pair.
    """
    from yosoi.observations.index.diff import ChangeKind, diff_indexes

    def _index_for(mutation: str, snapshot_id: str):
        return generated_html_workload(WORKLOAD, render_mutable_page(mutation), snapshot_id).index

    base = _index_for('base', 'capture-base')

    unchanged_again = diff_indexes(base, _index_for('base', 'capture-base-again'))
    assert unchanged_again.changes == (), 'a re-capture of an unchanged page must diff to nothing'
    assert unchanged_again.unchanged > 0

    # Inserting a section near the top of <body> is the row that justifies anchoring: a
    # root-absolute address space loses every reference below the insertion; this loses none.
    inserted = diff_indexes(base, _index_for('section_above', 'capture-section-above'))
    assert not inserted.of_kind(ChangeKind.REMOVED), 'an insertion above must remove no identity'
    assert inserted.of_kind(ChangeKind.ADDED), 'the inserted section is itself new'

    # A new row lands inside a collapsed region, so it costs no new entry — the region's own
    # summary moves instead. Compression and diffing have to agree about that or a QA reader
    # would see "nothing added" for a page that grew.
    row = diff_indexes(base, _index_for('row_inserted', 'capture-row-inserted'))
    assert not row.of_kind(ChangeKind.ADDED)
    assert not row.of_kind(ChangeKind.REMOVED)
    assert row.of_kind(ChangeKind.CHANGED), 'the region summary must report the new member'

    # Restyling loses class-anchored identities. Those are a removal AND an addition, never a
    # modification: nothing in the evidence says the new anchor names the old thing.
    restyled = diff_indexes(base, _index_for('class_restyled', 'capture-class-restyled'))
    assert restyled.of_kind(ChangeKind.REMOVED)
    assert restyled.of_kind(ChangeKind.ADDED)
    assert len(restyled.of_kind(ChangeKind.REMOVED)) == len(restyled.of_kind(ChangeKind.ADDED))

    for diff in (unchanged_again, inserted, row, restyled):
        assert diff.without_identity_before == diff.without_identity_after
        assert 'were NOT compared' in diff.describe(), 'unanchorable entries must stay visible'

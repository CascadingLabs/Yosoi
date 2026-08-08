"""Books to Scrape, frozen: the clean SSR dogfood target for source-HTML pruning."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.boss_fights.conftest import HtmlWorkload
from yosoi.observations.index.inspect import InspectionBudget

WORKLOAD = Path(__file__).parent


@pytest.fixture(scope='module')
def books(html_workload: Callable[[Path, str], HtmlWorkload]) -> HtmlWorkload:
    """Assemble the frozen Books to Scrape workload once per module."""
    return html_workload(WORKLOAD, 'books_toscrape.html')


def test_frozen_artifact_matches_its_manifest_digest(books: HtmlWorkload) -> None:
    assert books.snapshot.artifacts[0].sha256 == books.manifest['artifact_sha256']


def test_every_required_declaration_is_addressable_in_one_hop(books: HtmlWorkload) -> None:
    unreachable = []
    for evidence in books.ground_truth['required_evidence']:
        ordinals = books.entries_reaching(evidence['oracle_xpath'])
        if not ordinals:
            unreachable.append(evidence['id'])
            continue
        detail = books.inspect_bytes(ordinals[0]).decode(errors='replace')
        expected = evidence.get('oracle_contains')
        if expected and expected.lower() not in detail.lower():
            unreachable.append(f'{evidence["id"]} (address resolved, evidence absent)')
    assert not unreachable, f'required declarations unreachable from the index: {unreachable}'


def test_index_is_an_order_of_magnitude_smaller_than_the_document(books: HtmlWorkload) -> None:
    total = sum(view.stats.output_bytes for view in books.views)

    assert total <= books.manifest['budget_output_bytes']
    assert len(books.data) / total >= 10


def test_repeated_records_cost_one_region_not_twenty_entries(books: HtmlWorkload) -> None:
    """The headline case: N identical records must not buy N index slots."""
    from lxml import html as lxml_html

    expected = books.ground_truth['required_region'][0]
    records = lxml_html.fromstring(books.data).xpath(expected['oracle_xpath'])
    assert len(records) == expected['expected_members'], 'the frozen capture no longer holds the expected records'

    regions = books.regions_reaching(expected['oracle_xpath'])
    assert regions, 'the product region is unreachable from the index'
    region = books.index.entries[regions[0]]
    assert region.coverage is not None
    assert region.coverage.observed == expected['expected_members']
    assert region.coverage.complete, 'static HTML holds every member it has'
    # One region entry, not one per record — and 2 entries in total, the region plus its
    # exemplar member, for all 20 records.
    assert len(regions) == 1
    assert len(books.entries_reaching(expected['oracle_xpath'])) == 2


def test_every_record_stays_reachable_through_the_region(books: HtmlWorkload) -> None:
    """Collapsing must not cost reachability: each member is one `expand` hop away."""
    expected = books.ground_truth['required_region'][0]
    region_ordinal = books.regions_reaching(expected['oracle_xpath'])[0]

    page = books.expand(region_ordinal)

    assert len(page.members) == expected['expected_members']
    assert not page.truncated
    assert all(member.stable for member in page.members), 'members must be addressed durably, not by position'
    # And the address actually resolves back to that exact record.
    detail = books.inspector.inspect(page.members[1].ref, InspectionBudget()).content.decode(errors='replace')
    assert 'Tipping the Velvet' in detail


def test_region_expansion_is_bounded_and_pages(books: HtmlWorkload) -> None:
    expected = books.ground_truth['required_region'][0]
    region_ordinal = books.regions_reaching(expected['oracle_xpath'])[0]

    first = books.expand(region_ordinal, InspectionBudget(max_items=5))
    second = books.expand(region_ordinal, InspectionBudget(max_items=5), offset=5)

    assert len(first.members) == 5
    assert first.truncated
    assert [member.ordinal for member in second.members] == [5, 6, 7, 8, 9]
    assert {member.ref for member in first.members}.isdisjoint({member.ref for member in second.members})

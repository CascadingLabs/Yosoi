"""Regression coverage for typed repeated-root replay."""

from datetime import datetime, timezone

from rich.console import Console

import yosoi as ys
from yosoi.core.pipeline import Pipeline
from yosoi.core.resolve import build_cache_from_selectors, resolve
from yosoi.models.needs_discovery import NeedsDiscovery
from yosoi.models.snapshot import SelectorSnapshot


class PricingPlan(ys.Contract):
    name: str = ys.Title()
    price: str = ys.Field(description='Plan price')


HTML = """\
<html><body>
  <section class="plan" data-row="a"><h2>Free</h2><span class="price">$0</span></section>
  <section class="plan" data-row="b"><h2>Hobby</h2><span class="price">$9</span></section>
  <section class="plan" data-row="c"><h2>Pro</h2><span class="price">$19</span></section>
  <section class="plan" data-row="d"><h2>Enterprise</h2><span class="price">Call us</span></section>
</body></html>
"""

FIELD_SELECTORS = {
    'name': {'primary': {'type': 'css', 'value': 'h2'}},
    'price': {'primary': {'type': 'css', 'value': '.price'}},
}


def test_cached_replay_css_root_extracts_all_repeated_items() -> None:
    selectors = {**FIELD_SELECTORS, 'root': {'primary': {'type': 'css', 'value': '.plan'}}}

    records = resolve(
        PricingPlan.to_spec(),
        HTML,
        build_cache_from_selectors('example.test', PricingPlan.to_spec().fingerprint, selectors),
        'example.test',
        url='https://example.test/pricing',
    )

    assert not isinstance(records, NeedsDiscovery)
    assert len(records) == 4
    assert [record['name'] for record in records] == ['Free', 'Hobby', 'Pro', 'Enterprise']


def test_cached_replay_xpath_root_extracts_all_repeated_items_without_string_inference() -> None:
    selectors = {
        **FIELD_SELECTORS,
        'root': {'primary': {'type': 'xpath', 'value': './/section[@data-row]'}},
    }

    records = resolve(
        PricingPlan.to_spec(),
        HTML,
        build_cache_from_selectors('example.test', PricingPlan.to_spec().fingerprint, selectors),
        'example.test',
        url='https://example.test/pricing',
    )

    assert not isinstance(records, NeedsDiscovery)
    assert len(records) == 4
    assert records[-1]['price'] == 'Call us'


def test_cache_replay_cardinality_drop_reports_quality_issue() -> None:
    stub = Pipeline.__new__(Pipeline)
    stub.contract = PricingPlan
    stub.console = Console(quiet=True)
    stub.last_quality_status = 'unknown'
    stub.last_quality_issues = []
    stub.last_expected_record_count = None
    snapshots = {
        'name': SelectorSnapshot(
            primary={'type': 'css', 'value': 'h2'},
            discovered_at=datetime.now(timezone.utc),
            discovery_record_count=4,
            discovery_field_coverage={'name': 4, 'price': 4},
        )
    }

    stub._evaluate_replay_quality([{'name': 'Free', 'price': '$0'}, {'name': 'Hobby', 'price': '$9'}], snapshots)

    assert stub.last_quality_status == 'partial'
    assert stub.last_expected_record_count == 4
    assert any('record_count dropped' in issue for issue in stub.last_quality_issues)

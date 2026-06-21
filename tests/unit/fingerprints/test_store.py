"""Tests for the long-term fingerprint cache/audit store."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

import yosoi as ys
from yosoi.fingerprints import (
    FingerprintClassificationRecord,
    FingerprintFieldReferenceRecord,
    FingerprintPageRecord,
    FingerprintReferenceRecord,
    FingerprintStore,
    compare_field_reference,
    root_scope,
    route_template,
)
from yosoi.fingerprints.store import fingerprint_store_path
from yosoi.models.selectors import SelectorEntry

pytestmark = pytest.mark.unit

_HTML = """
<html><body><main class="catalog">
  <section class="hero"><h1>Catalog</h1><p>Intro</p></section>
  <section class="grid"><article class="card"><h2>Hammer</h2><a href="/hammer">View</a></article></section>
  <footer><nav><a href="/help">Help</a></nav></footer>
</main></body></html>
"""

_RICH_HTML = """
<html><body><main class="catalog">
  <section class="hero"><h1>Catalog</h1><p>Intro</p></section>
  <section class="filters"><form><input name="q"><button>Go</button></form></section>
  <section class="grid"><article class="card"><h2>Hammer</h2><a href="/hammer">View</a><img src="x"></article></section>
  <aside class="promo"><ul><li>One</li><li>Two</li></ul></aside>
  <footer><nav><a href="/help">Help</a></nav></footer>
</main></body></html>
"""


def test_default_store_path_uses_singular_dot_yosoi_fingerprint_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    path = fingerprint_store_path()

    assert path == tmp_path / '.yosoi' / 'fingerprint'
    assert path.is_dir()


def test_page_fingerprint_cache_round_trips_without_raw_html(tmp_path: Path) -> None:
    store = FingerprintStore(tmp_path)
    fp = ys.fingerprint(_HTML)
    record = FingerprintPageRecord(url='https://example.test/catalog', fingerprint=fp, fetch_tier='simple')

    path = store.save_page(record)
    loaded = store.load_page('https://example.test/catalog')

    assert path == store.page_path('https://example.test/catalog')
    assert loaded == record
    assert _HTML not in path.read_text(encoding='utf-8')


def test_reference_records_are_namespaced_by_contract_fingerprint(tmp_path: Path) -> None:
    store = FingerprintStore(tmp_path)
    fp = ys.fingerprint(_HTML)
    record = FingerprintReferenceRecord(
        reference_id='l1-product-catalog',
        label='L1 Product catalog',
        url='https://qscrape.dev/l1/eshop/catalog',
        fingerprint=fp,
        contract_name='Product',
        contract_fingerprint='abc123',
    )

    path = store.save_reference(record)

    assert path == tmp_path / 'references' / 'abc123' / 'l1-product-catalog.json'
    assert store.load_reference('l1-product-catalog', contract_fingerprint='abc123') == record
    assert store.list_references(contract_fingerprint='abc123') == [record]


def test_route_template_normalizes_content_identity() -> None:
    assert route_template('https://example.test/products/12345?ref=ad') == 'example.test/products/{id}'
    assert route_template('https://example.test/products/67890') == 'example.test/products/{id}'


def test_root_scope_preserves_selector_family() -> None:
    dom = root_scope('.product-card', contract_name='Product')
    ax = root_scope({'type': 'role', 'value': 'listitem', 'name': 'Product', 'nth': 0})
    visual = root_scope({'type': 'visual', 'value': 'card', 'x': 10, 'y': 20})

    assert dom.kind == 'dom'
    assert ax.kind == 'accessibility'
    assert visual.kind == 'visual'
    assert dom.signature != ax.signature


def test_field_reference_records_round_trip_and_compare(tmp_path: Path) -> None:
    store = FingerprintStore(tmp_path)
    fp = ys.fingerprint(_RICH_HTML)
    reference = FingerprintFieldReferenceRecord(
        reference_id='product-name',
        label='Product name in card root',
        url='https://example.test/products/12345',
        route_template=route_template('https://example.test/products/67890'),
        fingerprint=fp,
        contract_name='Product',
        contract_fingerprint='product-fp',
        field_name='name',
        yosoi_type='title',
        root=root_scope('.product-card', contract_name='Product'),
        selector=SelectorEntry(type='css', value='h2'),
    )

    path = store.save_field_reference(reference)
    loaded = store.load_field_reference('product-name', field_name='name', contract_fingerprint='product-fp')
    similarity = compare_field_reference(
        candidate_fingerprint=fp,
        candidate_url='https://example.test/products/99999',
        candidate_field_name='name',
        candidate_yosoi_type='title',
        candidate_root='.product-card',
        candidate_contract_name='Product',
        candidate_contract_fingerprint='product-fp',
        reference=reference,
    )

    assert path == tmp_path / 'references' / 'product-fp' / 'fields' / 'name' / 'product-name.json'
    assert loaded == reference
    assert store.list_field_references(contract_fingerprint='product-fp') == [reference]
    assert similarity.score == 1.0
    assert similarity.page.skeleton.score == 1.0
    assert similarity.field_scope.root.score == 1.0
    assert similarity.field_scope.same_field_scope is True


def test_classification_audit_appends_jsonl_events(tmp_path: Path) -> None:
    store = FingerprintStore(tmp_path)
    left = ys.fingerprint(_RICH_HTML)
    right = ys.fingerprint(_RICH_HTML.replace('Hammer', 'Tongs'))
    similarity = left.similarity(right)
    record = FingerprintClassificationRecord.from_similarity(
        run_id='run-1',
        candidate_url='https://example.test/catalog?cat=forge',
        candidate_label='candidate catalog',
        best_reference_id='l1-product-catalog',
        best_reference_label='L1 Product catalog',
        similarity=similarity,
        decision='reuse',
        evidence=('same skeleton', 'same semantic features'),
    )

    path = store.append_classification(record)
    store.append_classification(record.model_copy(update={'decision': 'quarantine'}))
    lines = path.read_text(encoding='utf-8').splitlines()

    assert len(lines) == 2
    assert json.loads(lines[0])['score'] == 1.0
    assert [event.decision for event in store.load_classifications('run-1')] == ['reuse', 'quarantine']


def test_plural_fingerprints_package_does_not_clobber_public_fingerprint_api() -> None:
    before = ys.fingerprint

    importlib.import_module('yosoi.fingerprints.store')

    assert ys.fingerprint is before
    assert callable(ys.fingerprint)

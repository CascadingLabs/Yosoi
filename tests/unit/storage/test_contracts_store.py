"""Tests for local content-addressed contracts store (CAS-122)."""

from __future__ import annotations

import json

import pytest

from yosoi.models.defaults import NewsArticle, Product
from yosoi.models.spec import CURRENT_SCHEMA_VERSION, ContractSpec
from yosoi.storage.contracts_store import ContractCollisionError, ContractStore


@pytest.fixture
def store(tmp_path) -> ContractStore:
    return ContractStore(str(tmp_path / 'contracts'))


@pytest.fixture
def news_spec() -> ContractSpec:
    return NewsArticle.to_spec()


@pytest.fixture
def product_spec() -> ContractSpec:
    return Product.to_spec()


class TestAdd:
    def test_add_creates_spec_file(self, store, news_spec):
        fp = store.add(news_spec)
        assert (store._root / f'{fp}.json').exists()

    def test_add_creates_names_json(self, store, news_spec):
        store.add(news_spec)
        assert store._names_path.exists()

    def test_add_registers_alias(self, store, news_spec):
        fp = store.add(news_spec)
        names = json.loads(store._names_path.read_text())
        assert names.get('NewsArticle') == fp

    def test_add_custom_alias(self, store, news_spec):
        fp = store.add(news_spec, name='MyAlias')
        names = json.loads(store._names_path.read_text())
        assert names.get('MyAlias') == fp

    def test_add_idempotent_same_name_same_fp(self, store, news_spec):
        fp1 = store.add(news_spec)
        fp2 = store.add(news_spec)  # same name + same fp → no-op
        assert fp1 == fp2

    def test_add_collision_same_name_different_fp_raises(self, store, news_spec, product_spec):
        store.add(news_spec, name='shared')
        with pytest.raises(ContractCollisionError) as exc_info:
            store.add(product_spec, name='shared')
        err = exc_info.value
        assert err.name == 'shared'
        assert err.existing_fp == news_spec.fingerprint
        assert err.new_fp == product_spec.fingerprint

    def test_add_different_name_same_fp_ok(self, store, news_spec):
        fp1 = store.add(news_spec, name='A')
        fp2 = store.add(news_spec, name='B')
        assert fp1 == fp2
        names = json.loads(store._names_path.read_text())
        assert names['A'] == fp1
        assert names['B'] == fp1


class TestGet:
    def test_get_by_name(self, store, news_spec):
        fp = store.add(news_spec)
        retrieved = store.get('NewsArticle')
        assert retrieved.fingerprint == fp

    def test_get_by_fingerprint(self, store, news_spec):
        fp = store.add(news_spec)
        retrieved = store.get(fp)
        assert retrieved.fingerprint == fp

    def test_get_unknown_raises(self, store):
        with pytest.raises(KeyError):
            store.get('NonExistent')


class TestList:
    def test_list_empty(self, store):
        assert store.list_aliases() == []

    def test_list_returns_sorted_aliases(self, store, news_spec, product_spec):
        store.add(product_spec, name='Product')
        store.add(news_spec, name='NewsArticle')
        pairs = store.list_aliases()
        names = [n for n, _ in pairs]
        assert names == sorted(names)

    def test_fingerprints_returns_all_fps(self, store, news_spec, product_spec):
        fp1 = store.add(news_spec)
        fp2 = store.add(product_spec)
        fps = store.fingerprints()
        assert fp1 in fps
        assert fp2 in fps


class TestLint:
    def test_lint_valid_spec_clean(self, store, news_spec):
        assert store.lint(news_spec) == []

    def test_lint_future_version_error(self, store):
        # Use model_construct to bypass the too-new validation — lint should catch it
        spec = ContractSpec.model_construct(name='X', fields={}, schema_version=CURRENT_SCHEMA_VERSION + 1)
        errors = store.lint(spec)
        assert len(errors) >= 1
        assert 'schema_version' in errors[0].lower()

    def test_lint_version_zero_error(self, store):
        spec = ContractSpec.model_construct(name='X', fields={}, schema_version=0)
        errors = store.lint(spec)
        assert len(errors) >= 1


class TestMigrate:
    def test_migrate_current_version_no_op(self, store, news_spec):
        migrated = store.migrate(news_spec)
        assert migrated.schema_version == CURRENT_SCHEMA_VERSION
        assert migrated.fingerprint == news_spec.fingerprint

    def test_migrate_invalid_version_raises(self, store):
        spec = ContractSpec.model_construct(name='X', fields={}, schema_version=0)
        with pytest.raises(ValueError, match='too old'):
            store.migrate(spec)

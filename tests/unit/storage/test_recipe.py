"""Unit tests for the recipe system: RecipeBundle, SelectorKey, SelectorStorage
preloaded path, and load_recipe.

Place this file at:
    tests/unit/storage/test_recipe.py

No network, no LLM, no disk I/O except tempfiles.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from yosoi.models.recipe import RecipeBundle
from yosoi.models.snapshot import SelectorSnapshot, SnapshotMap, SnapshotStatus
from yosoi.models.spec import ContractSpec, FieldSpec
from yosoi.storage.persistence import SelectorStorage
from yosoi.storage.recipe_loader import is_recipe_source, load_recipe
from yosoi.storage.selector_key import SelectorKey

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_spec(name: str = 'Product') -> ContractSpec:
    return ContractSpec(
        name=name,
        fields={
            'name': FieldSpec(yosoi_type='title'),
            'price': FieldSpec(yosoi_type='price'),
        },
    )


def _make_snapshot(css_value: str) -> SelectorSnapshot:
    return SelectorSnapshot(
        primary={'type': 'css', 'value': css_value},
        discovered_at=datetime.now(timezone.utc),
        status=SnapshotStatus.ACTIVE,
    )


def _make_snap_map(url: str = 'https://example.com', domain: str = 'example.com') -> SnapshotMap:
    return SnapshotMap(
        url=url,
        domain=domain,
        snapshots={
            'name': _make_snapshot('h1.product-name'),
            'price': _make_snapshot('.price'),
        },
    )


def _make_bundle() -> RecipeBundle:
    spec = _make_spec()
    snap_map = _make_snap_map()
    return RecipeBundle(contract=spec, selectors={'example.com': snap_map})


# ---------------------------------------------------------------------------
# RecipeBundle — round-trip and integrity
# ---------------------------------------------------------------------------


class TestRecipeBundleIntegrity:
    def test_round_trip_preserves_contract_name(self):
        bundle = _make_bundle()
        json_str = bundle.to_json()
        reloaded = RecipeBundle.model_validate_json(json_str)
        assert reloaded.contract.name == bundle.contract.name

    def test_round_trip_preserves_recipe_id(self):
        bundle = _make_bundle()
        json_str = bundle.to_json()
        reloaded = RecipeBundle.model_validate_json(json_str)
        assert reloaded.recipe_id == bundle.recipe_id

    def test_round_trip_preserves_domain_keys(self):
        bundle = _make_bundle()
        reloaded = RecipeBundle.model_validate_json(bundle.to_json())
        assert set(reloaded.selectors.keys()) == {'example.com'}

    def test_verify_integrity_passes_on_untampered_bundle(self):
        bundle = _make_bundle()
        # Should not raise.
        bundle.verify_integrity()

    def test_verify_integrity_raises_on_tampered_contract_name(self):
        bundle = _make_bundle()
        json_str = bundle.to_json()
        raw = json.loads(json_str)
        raw['contract']['name'] = 'Tampered'
        tampered = RecipeBundle.model_validate(raw)
        with pytest.raises(ValueError, match='integrity'):
            tampered.verify_integrity()

    def test_recipe_id_is_sha256_prefixed(self):
        bundle = _make_bundle()
        assert bundle.recipe_id.startswith('sha256:')

    def test_recipe_id_is_stable_across_serializations(self):
        bundle = _make_bundle()
        id1 = bundle.recipe_id
        reloaded = RecipeBundle.model_validate_json(bundle.to_json())
        assert reloaded.recipe_id == id1

    def test_verify_schema_passes_for_current_version(self):
        bundle = _make_bundle()
        bundle.verify_schema()  # must not raise

    def test_verify_schema_raises_for_unknown_version(self):
        bundle = _make_bundle()
        # Mutate via model_copy to avoid re-triggering the validator
        bad = bundle.model_copy(update={'schema_version': 'yosoi.recipe.v99'})
        with pytest.raises(ValueError, match='schema_version'):
            bad.verify_schema()

    def test_verify_alignment_returns_empty_when_all_fields_covered(self):
        bundle = _make_bundle()
        warnings = bundle.verify_alignment()
        assert warnings == []

    def test_verify_alignment_warns_about_missing_fields(self):
        spec = ContractSpec(
            name='Wide',
            fields={
                'name': FieldSpec(yosoi_type='title'),
                'price': FieldSpec(yosoi_type='price'),
                'rating': FieldSpec(yosoi_type='rating'),  # not in snapshots
            },
        )
        snap_map = _make_snap_map()
        bundle = RecipeBundle(contract=spec, selectors={'example.com': snap_map})
        warnings = bundle.verify_alignment()
        assert any('rating' in w for w in warnings)

    def test_snapshots_for_domain_exact_match(self):
        bundle = _make_bundle()
        result = bundle.snapshots_for_domain('example.com')
        assert result is not None
        assert 'name' in result.snapshots

    def test_snapshots_for_domain_subdomain_fallback(self):
        bundle = _make_bundle()
        result = bundle.snapshots_for_domain('www.example.com')
        assert result is not None

    def test_snapshots_for_domain_returns_none_for_unknown(self):
        bundle = _make_bundle()
        assert bundle.snapshots_for_domain('other.com') is None

    def test_from_parts_builds_valid_bundle(self):
        import yosoi as ys
        from yosoi.models.contract import Contract

        class Product(Contract):
            name: str = ys.Title(description='Product name')
            price: float = ys.Price(description='Product price')

        snap_map = _make_snap_map()
        bundle = RecipeBundle.from_parts(Product, {'example.com': snap_map})
        assert bundle.contract.name == 'Product'
        assert 'name' in bundle.contract.fields
        bundle.verify_integrity()

    def test_save_and_load_round_trips(self, tmp_path):
        bundle = _make_bundle()
        path = str(tmp_path / 'recipe.json')
        bundle.save(path)
        loaded = RecipeBundle.load(path)
        assert loaded.contract.name == bundle.contract.name
        assert loaded.recipe_id == bundle.recipe_id

    def test_load_raises_on_tampered_file(self, tmp_path):
        bundle = _make_bundle()
        path = str(tmp_path / 'recipe.json')
        bundle.save(path)

        with open(path) as f:
            raw = json.load(f)
        raw['contract']['name'] = 'Hacked'
        with open(path, 'w') as f:
            json.dump(raw, f)

        with pytest.raises(ValueError, match='integrity'):
            RecipeBundle.load(path)

    def test_summary_contains_expected_keys(self):
        bundle = _make_bundle()
        s = bundle.summary()
        assert s['contract'] == 'Product'
        assert 'example.com' in s['domains']
        assert 'name' in s['fields']
        assert 'price' in s['fields']


# ---------------------------------------------------------------------------
# SelectorKey — filename generation and parsing
# ---------------------------------------------------------------------------


class TestSelectorKey:
    def test_to_filename_basic(self):
        key = SelectorKey(domain='example.com', contract_sig='v3:abc123')
        assert key.to_filename() == 'selectors_example_com__v3_abc123.json'

    def test_to_filename_with_page_shape(self):
        key = SelectorKey(domain='example.com', contract_sig='v3:abc123', page_shape='s1:4e9f8fa8')
        assert key.to_filename() == 'selectors_example_com__v3_abc123__s1_4e9f8fa8.json'

    def test_to_filename_stem_no_extension(self):
        key = SelectorKey(domain='example.com', contract_sig='v3:abc123')
        stem = key.to_filename_stem()
        assert not stem.endswith('.json')
        assert 'selectors_' in stem

    def test_parse_filename_v2_round_trip(self):
        key = SelectorKey(domain='example.com', contract_sig='v3:abc123')
        filename = key.to_filename()
        parsed = SelectorKey.parse_filename(filename)
        assert parsed is not None
        assert parsed.contract_sig == 'v3_abc123'  # colons replaced by _safe_seg

    def test_parse_filename_v3_with_page_shape(self):
        key = SelectorKey(domain='example.com', contract_sig='v3:abc123', page_shape='s1:4e9f8fa8')
        parsed = SelectorKey.parse_filename(key.to_filename())
        assert parsed is not None
        assert parsed.page_shape == 's1_4e9f8fa8'

    def test_parse_filename_legacy_no_contract_sig(self):
        legacy = SelectorKey.parse_filename('selectors_example_com.json')
        assert legacy is not None
        assert legacy.is_legacy is True
        assert legacy.contract_sig == ''

    def test_parse_filename_returns_none_for_non_selector_file(self):
        assert SelectorKey.parse_filename('content_example_com.json') is None

    def test_parse_filename_returns_none_for_wrong_extension(self):
        assert SelectorKey.parse_filename('selectors_example_com.txt') is None

    def test_is_legacy_false_when_contract_sig_present(self):
        key = SelectorKey(domain='example.com', contract_sig='v3:abc123')
        assert key.is_legacy is False

    def test_has_page_shape_false_by_default(self):
        key = SelectorKey(domain='example.com', contract_sig='v3:abc123')
        assert key.has_page_shape is False

    def test_has_page_shape_true_when_set(self):
        key = SelectorKey(domain='example.com', contract_sig='v3:abc123', page_shape='s1:xyz')
        assert key.has_page_shape is True

    def test_from_domain_convenience_constructor(self):
        key = SelectorKey.from_domain('example.com', 'v3:abc123')
        assert key.domain == 'example.com'
        assert key.contract_sig == 'v3:abc123'
        assert key.page_shape is None

    def test_colons_and_slashes_are_replaced_in_filename(self):
        key = SelectorKey(domain='example.com', contract_sig='v3:abc/123')
        filename = key.to_filename()
        assert ':' not in filename
        assert '/' not in filename


# ---------------------------------------------------------------------------
# SelectorStorage — preloaded path
# ---------------------------------------------------------------------------


class TestSelectorStoragePreloaded:
    @pytest.fixture
    def storage_with_preload(self, tmp_path, mocker):
        selector_dir = tmp_path / 'selectors'
        content_dir = tmp_path / 'content'
        selector_dir.mkdir()
        content_dir.mkdir()
        mocker.patch(
            'yosoi.storage.persistence.init_yosoi',
            side_effect=[selector_dir, content_dir],
        )
        snap_map = _make_snap_map()
        return SelectorStorage(preloaded={'example.com': snap_map})

    async def test_load_snapshots_returns_preloaded_data(self, storage_with_preload):
        result = await storage_with_preload.load_snapshots('example.com')
        assert result is not None
        assert 'name' in result
        assert 'price' in result

    async def test_load_snapshots_subdomain_fallback(self, storage_with_preload):
        result = await storage_with_preload.load_snapshots('www.example.com')
        assert result is not None

    async def test_load_snapshots_unknown_domain_returns_none(self, storage_with_preload):
        result = await storage_with_preload.load_snapshots('other.com')
        assert result is None

    async def test_record_verdict_is_noop_for_preloaded_domain(self, storage_with_preload):
        from yosoi.models.snapshot import CacheVerdict

        # Should not raise and should not attempt disk I/O.
        await storage_with_preload.record_verdict('example.com', 'name', CacheVerdict.FRESH)

    def test_has_preloaded_true_when_data_provided(self, storage_with_preload):
        assert storage_with_preload.has_preloaded() is True

    def test_has_preloaded_false_for_normal_storage(self, tmp_path, mocker):
        selector_dir = tmp_path / 'selectors'
        content_dir = tmp_path / 'content'
        selector_dir.mkdir()
        content_dir.mkdir()
        mocker.patch(
            'yosoi.storage.persistence.init_yosoi',
            side_effect=[selector_dir, content_dir],
        )
        storage = SelectorStorage()
        assert storage.has_preloaded() is False

    async def test_selector_exists_true_for_preloaded_domain(self, storage_with_preload):
        assert await storage_with_preload.selector_exists('example.com') is True

    async def test_selector_exists_true_for_preloaded_subdomain(self, storage_with_preload):
        assert await storage_with_preload.selector_exists('www.example.com') is True


# ---------------------------------------------------------------------------
# is_recipe_source
# ---------------------------------------------------------------------------


class TestIsRecipeSource:
    def test_https_url_is_recipe_source(self):
        assert is_recipe_source('https://raw.githubusercontent.com/foo/bar/recipe.json')

    def test_http_url_is_recipe_source(self):
        assert is_recipe_source('http://example.com/recipe.json')

    def test_contract_name_is_not_recipe_source(self):
        assert not is_recipe_source('Product')

    def test_python_module_path_is_not_recipe_source(self):
        assert not is_recipe_source('path/to/file.py:MyContract')

    def test_nonexistent_json_path_is_not_recipe_source(self):
        assert not is_recipe_source('/nonexistent/path/recipe.json')

    def test_existing_json_file_is_recipe_source(self, tmp_path):
        p = tmp_path / 'recipe.json'
        p.write_text('{}')
        assert is_recipe_source(str(p))

    def test_existing_non_json_file_is_not_recipe_source(self, tmp_path):
        p = tmp_path / 'recipe.txt'
        p.write_text('{}')
        assert not is_recipe_source(str(p))


# ---------------------------------------------------------------------------
# load_recipe — local file path
# ---------------------------------------------------------------------------


class TestLoadRecipeLocalFile:
    async def test_load_valid_recipe_file(self, tmp_path):
        bundle = _make_bundle()
        path = str(tmp_path / 'recipe.json')
        bundle.save(path)

        loaded = await load_recipe(path)
        assert loaded.contract.name == bundle.contract.name

    async def test_load_preserves_recipe_id(self, tmp_path):
        bundle = _make_bundle()
        path = str(tmp_path / 'recipe.json')
        bundle.save(path)

        loaded = await load_recipe(path)
        assert loaded.recipe_id == bundle.recipe_id

    async def test_load_tampered_file_raises_integrity_error(self, tmp_path):
        bundle = _make_bundle()
        path = str(tmp_path / 'recipe.json')
        bundle.save(path)

        with open(path) as f:
            raw = json.load(f)
        raw['contract']['name'] = 'Hacked'
        with open(path, 'w') as f:
            json.dump(raw, f)

        with pytest.raises(ValueError, match='integrity'):
            await load_recipe(path)

    async def test_load_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            await load_recipe(str(tmp_path / 'nonexistent.json'))

    async def test_load_invalid_json_raises_value_error(self, tmp_path):
        path = str(tmp_path / 'bad.json')
        with open(path, 'w') as f:
            f.write('NOT VALID JSON')
        with pytest.raises(ValueError, match='Failed to parse'):
            await load_recipe(path)

    async def test_load_empty_selectors_raises_value_error(self, tmp_path):
        # Build a bundle then strip out its selectors before saving.
        bundle = _make_bundle()
        raw = json.loads(bundle.to_json())
        raw['selectors'] = {}
        # Recompute recipe_id so integrity passes but selectors are empty.
        empty_bundle = RecipeBundle.model_validate(raw)
        # Manually fix the recipe_id to match the empty-selectors content.
        raw['recipe_id'] = empty_bundle._compute_id()
        path = str(tmp_path / 'empty.json')
        with open(path, 'w') as f:
            json.dump(raw, f)

        with pytest.raises(ValueError, match='no selector'):
            await load_recipe(path)

    async def test_load_wrong_schema_version_raises_value_error(self, tmp_path):
        bundle = _make_bundle()
        raw = json.loads(bundle.to_json())
        raw['schema_version'] = 'yosoi.recipe.v99'
        # Recompute recipe_id so integrity check doesn't fire first.
        bad_bundle = RecipeBundle.model_validate(raw)
        raw['recipe_id'] = bad_bundle._compute_id()
        path = str(tmp_path / 'old.json')
        with open(path, 'w') as f:
            json.dump(raw, f)

        with pytest.raises(ValueError, match='schema_version'):
            await load_recipe(path)

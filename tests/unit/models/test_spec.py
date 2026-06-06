"""Tests for ContractSpec round-trip + structural fingerprint (CAS-97)."""

from __future__ import annotations

import json

import pytest

from yosoi import types as ys
from yosoi.models.contract import Contract
from yosoi.models.defaults import JobPosting, NewsArticle, Product, Video
from yosoi.models.spec import CURRENT_SCHEMA_VERSION, ContractSpec, FieldSpec
from yosoi.utils.contracts import resolve_contract

# ── fixtures ─────────────────────────────────────────────────────────────────


class SimpleContract(Contract):
    title: str = ys.Title(description='Page title')
    price: float | None = ys.Price(description='Item price')


class FrozenContract(Contract):
    name: str = ys.Field(frozen=True, description='Product name')
    url: str = ys.Field(selector='a.buy', description='Buy link')


# ── round-trip identity ───────────────────────────────────────────────────────


class TestRoundTrip:
    @pytest.mark.parametrize('contract_cls', [NewsArticle, Product, Video, JobPosting])
    def test_builtin_round_trip(self, contract_cls):
        spec = contract_cls.to_spec()
        rehydrated = Contract.from_spec(spec)
        assert set(rehydrated.model_fields) == set(contract_cls.model_fields)

    def test_round_trip_preserves_yosoi_type(self):
        spec = SimpleContract.to_spec()
        rehydrated = Contract.from_spec(spec)
        extra = rehydrated.model_fields['title'].json_schema_extra
        assert isinstance(extra, dict)
        assert extra.get('yosoi_type') == 'title'

    def test_round_trip_preserves_frozen(self):
        spec = FrozenContract.to_spec()
        rehydrated = Contract.from_spec(spec)
        extra = rehydrated.model_fields['name'].json_schema_extra
        assert isinstance(extra, dict)
        assert extra.get('yosoi_frozen') is True

    def test_round_trip_preserves_selector_override(self):
        spec = FrozenContract.to_spec()
        rehydrated = Contract.from_spec(spec)
        extra = rehydrated.model_fields['url'].json_schema_extra
        assert isinstance(extra, dict)
        assert extra.get('yosoi_selector') == 'a.buy'

    def test_json_serialization(self):
        spec = NewsArticle.to_spec()
        raw = json.loads(spec.model_dump_json())
        restored = ContractSpec.model_validate(raw)
        assert restored.fingerprint == spec.fingerprint

    def test_from_dict(self):
        spec = NewsArticle.to_spec()
        d = spec.model_dump()
        restored = ContractSpec.from_dict(d)
        assert restored.fingerprint == spec.fingerprint


# ── fingerprint dedup ─────────────────────────────────────────────────────────


class TestFingerprint:
    def test_same_fields_different_name_different_fingerprint(self):
        # P0: contract name is part of identity — a renamed contract is a distinct
        # cache slot (mirrors v2 contract_signature; the AdLink/OrganicLink fix).
        spec_a = NewsArticle.to_spec()
        spec_b = spec_a.model_copy(update={'name': 'AliasContract'})
        assert spec_a.fingerprint != spec_b.fingerprint

    def test_same_fields_different_doc_different_fingerprint(self):
        # P0: the contract-level docstring is the discovery-time intent disambiguator.
        spec_a = NewsArticle.to_spec()
        spec_b = spec_a.model_copy(update={'doc': 'A completely different intent.'})
        assert spec_a.fingerprint != spec_b.fingerprint

    def test_structurally_identical_different_intent_discriminated(self):
        # The motivating SERP case: AdLink vs OrganicLink — identical {url, title}
        # structure, distinguished ONLY by name + docstring intent.
        class AdLink(Contract):
            """A paid advertisement result link."""

            url: str = ys.Url(description='Link URL')
            title: str = ys.Title(description='Link title')

        class OrganicLink(Contract):
            """A natural (non-paid) organic search result link."""

            url: str = ys.Url(description='Link URL')
            title: str = ys.Title(description='Link title')

        assert AdLink.to_spec().fingerprint != OrganicLink.to_spec().fingerprint

    def test_same_fields_different_field_description_same_fingerprint(self):
        # Per-FIELD description stays advisory/excluded — only contract name+doc carry identity.
        spec_a = NewsArticle.to_spec()
        new_fields = dict(spec_a.fields)
        f = new_fields['headline']
        new_fields['headline'] = FieldSpec(**{**f.model_dump(), 'description': 'A very different description!'})
        spec_b = spec_a.model_copy(update={'fields': new_fields})
        assert spec_a.fingerprint == spec_b.fingerprint

    def test_one_field_difference_different_fingerprint(self):
        spec_a = NewsArticle.to_spec()
        new_fields = dict(spec_a.fields)
        f = new_fields['headline']
        # Change yosoi_type — this SHOULD produce a different fingerprint
        new_fields['headline'] = FieldSpec(**{**f.model_dump(), 'yosoi_type': 'body_text'})
        spec_b = spec_a.model_copy(update={'fields': new_fields})
        assert spec_a.fingerprint != spec_b.fingerprint

    def test_schema_version_is_included(self):
        spec_a = NewsArticle.to_spec()
        spec_b = spec_a.model_copy(update={'schema_version': 0})
        assert spec_a.fingerprint != spec_b.fingerprint

    def test_fingerprint_is_16_hex_chars(self):
        fp = NewsArticle.to_spec().fingerprint
        assert len(fp) == 16
        assert all(c in '0123456789abcdef' for c in fp)


# ── fail-fast validation ──────────────────────────────────────────────────────


class TestFailFast:
    def test_unknown_yosoi_type_raises(self):
        spec = ContractSpec(
            name='Bad',
            fields={'x': FieldSpec(yosoi_type='totally_made_up_type')},
        )
        with pytest.raises(ValueError, match='Unknown yosoi_type'):
            spec.to_contract()

    def test_unknown_validators_ref_raises(self):
        spec = ContractSpec(
            name='Bad',
            fields={'x': FieldSpec()},
            validators='does.not.exist:MyClass',
        )
        with pytest.raises((ImportError, ValueError)):
            spec.to_contract()

    def test_schema_version_too_new_raises(self):
        with pytest.raises(ValueError, match='newer than this yosoi version'):
            ContractSpec(name='X', fields={}, schema_version=CURRENT_SCHEMA_VERSION + 99)


# ── resolve_contract() accepts ContractSpec ───────────────────────────────────


class TestResolveContractSpec:
    def test_resolve_from_spec(self):
        spec = Product.to_spec()
        cls = resolve_contract(spec)
        assert set(cls.model_fields) == set(Product.model_fields)

    def test_resolve_from_dict(self):
        spec_dict = Product.to_spec().model_dump()
        cls = resolve_contract(spec_dict)
        assert set(cls.model_fields) == set(Product.model_fields)

    def test_identical_spec_returns_registered_contract(self):
        spec = NewsArticle.to_spec()
        cls = resolve_contract(spec)
        # Should return the ALREADY-REGISTERED NewsArticle, not a new anonymous class
        assert cls is NewsArticle

    def test_string_resolution_still_works(self):
        cls = resolve_contract('NewsArticle')
        assert cls is NewsArticle


class TestToContractPaths:
    """Cover specific branches in ContractSpec.to_contract()."""

    def test_to_contract_with_selector_override(self):
        spec = ContractSpec(
            name='WithSel',
            fields={'name': FieldSpec(yosoi_type='title', selector='h1.name')},
        )
        cls = spec.to_contract()
        extra = cls.model_fields['name'].json_schema_extra
        assert isinstance(extra, dict)
        assert extra.get('yosoi_selector') == 'h1.name'

    def test_to_contract_with_frozen(self):
        spec = ContractSpec(
            name='WithFrozen',
            fields={'name': FieldSpec(frozen=True)},
        )
        cls = spec.to_contract()
        extra = cls.model_fields['name'].json_schema_extra
        assert isinstance(extra, dict)
        assert extra.get('yosoi_frozen') is True

    def test_to_contract_with_optional_type(self):
        spec = ContractSpec(
            name='WithOpt',
            fields={'price': FieldSpec(yosoi_type='price', python_type='float', required=False)},
        )
        cls = spec.to_contract()
        assert 'price' in cls.model_fields

    def test_from_contract_with_root(self):
        import pydantic

        from yosoi.models.contract import Contract
        from yosoi.models.selectors import SelectorEntry

        class RootedContract(Contract):
            title: str = pydantic.Field(description='Title')

        RootedContract.root = SelectorEntry(type='css', value='.card')  # type: ignore[attr-defined]

        spec = ContractSpec.from_contract(RootedContract)
        assert spec.root is not None
        assert spec.root.get('value') == '.card'

    def test_to_contract_with_root(self):
        spec = ContractSpec(
            name='RootedSpec',
            fields={'title': FieldSpec()},
            root={'type': 'css', 'value': '.card'},
        )
        cls = spec.to_contract()
        assert cls.root is not None
        assert cls.root.value == '.card'

    def test_load_validators_bad_ref_format_raises(self):
        from yosoi.models.spec import _load_validators

        with pytest.raises(ImportError, match=r'module\.path:ClassName'):
            _load_validators('no_colon_here')

    def test_action_field_roundtrip(self):

        from yosoi import types as ys
        from yosoi.models.contract import Contract

        class ActContract(Contract):
            signals: dict = ys.js('(() => ({ok: true}))()', description='Signals')

        spec = ContractSpec.from_contract(ActContract)
        rehydrated = spec.to_contract()
        extra = rehydrated.model_fields['signals'].json_schema_extra
        assert isinstance(extra, dict)
        assert 'yosoi_action' in extra

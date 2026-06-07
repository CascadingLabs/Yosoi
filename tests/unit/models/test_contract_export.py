"""W5 regression tests: Contract.variant disambiguation + Contract.to_model export."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import BaseModel, Field

import yosoi as ys
from yosoi.models.contract import Contract
from yosoi.utils.signatures import contract_signature

# ---------------------------------------------------------------------------
# Contract.variant — NOTE #2 (declare redundant siblings, distinct signatures)
# ---------------------------------------------------------------------------


class _Link(Contract):
    """A link."""

    url: str = Field(description='The link URL')
    title: str = Field(description='The link text')


def test_variant_preserves_fields_and_sets_docstring():
    OrganicLink = _Link.variant('W5OrganicLink', 'A free/organic search result link.')
    AdLink = _Link.variant('W5AdLink', 'A paid/sponsored result link.')

    # Fields inherited verbatim.
    assert set(OrganicLink.model_fields) == {'url', 'title'}
    assert set(AdLink.model_fields) == {'url', 'title'}
    # Docstring becomes the disambiguating intent.
    assert OrganicLink.__doc__ == 'A free/organic search result link.'
    assert AdLink.__doc__ == 'A paid/sponsored result link.'


def test_variant_yields_distinct_signatures():
    """Two same-shape variants get DISTINCT signatures (the clobber fix)."""
    OrganicLink = _Link.variant('W5OrganicLink2', 'A free/organic search result link.')
    AdLink = _Link.variant('W5AdLink2', 'A paid/sponsored result link.')

    organic_sig = contract_signature(OrganicLink)
    ad_sig = contract_signature(AdLink)
    assert organic_sig != ad_sig
    # Both also differ from the base contract.
    assert contract_signature(_Link) not in {organic_sig, ad_sig}


def test_variant_rejects_empty_description():
    with pytest.raises(TypeError):
        _Link.variant('W5NoDesc', '   ')


def test_variant_rejects_base_name():
    with pytest.raises(ValueError, match='must differ'):
        _Link.variant('_Link', 'some description')


def test_variant_rejects_duplicate_registered_name():
    _Link.variant('W5DupName', 'first')
    with pytest.raises(ValueError, match='already registered'):
        _Link.variant('W5DupName', 'second')


# ---------------------------------------------------------------------------
# Contract.to_model — NOTE #1 (contract -> ODM/model export, no adapter)
# ---------------------------------------------------------------------------


class _MapsListingExtract(Contract):
    """A Google Maps business listing."""

    name: str = ys.Title(description='Business name')
    rating: str = ys.Rating(description='Star rating')
    phone: str = Field(description='Phone number')


def test_to_model_roundtrips_extraction_fields():
    Model = _MapsListingExtract.to_model(BaseModel, name='MapsDoc')
    assert issubclass(Model, BaseModel)
    assert set(Model.model_fields) >= {'name', 'rating', 'phone'}

    inst = Model(name='Cafe', rating='4.5', phone='555-0100')
    assert inst.name == 'Cafe'
    assert inst.rating == '4.5'


def test_to_model_default_name():
    Model = _MapsListingExtract.to_model()
    assert Model.__name__ == '_MapsListingExtractModel'


def test_to_model_yosoi_type_survives_in_json_schema():
    """yosoi_type rides along via json_schema_extra into the exported model."""
    Model = _MapsListingExtract.to_model(BaseModel, name='MapsDoc2')
    schema = Model.model_json_schema()
    # The rating field carries its yosoi_type in the JSON schema.
    rating = schema['properties']['rating']
    assert rating.get('yosoi_type') == 'rating'
    name = schema['properties']['name']
    assert name.get('yosoi_type') == 'title'


def test_to_model_adds_envelope_fields():
    Model = _MapsListingExtract.to_model(
        BaseModel,
        name='MapsDocEnvelope',
        run_id=(str, ...),
        captured_at=(datetime | None, None),
    )
    assert 'run_id' in Model.model_fields
    assert 'captured_at' in Model.model_fields

    inst = Model(name='X', rating='4', phone='1', run_id='r1')
    assert inst.run_id == 'r1'
    assert inst.captured_at is None


def test_to_model_include_scopes_fields():
    Model = _MapsListingExtract.to_model(BaseModel, name='MapsName', include={'name'})
    assert set(Model.model_fields) == {'name'}


def test_to_model_exclude_drops_fields():
    Model = _MapsListingExtract.to_model(BaseModel, name='MapsNoPhone', exclude={'phone'})
    assert 'phone' not in Model.model_fields
    assert {'name', 'rating'} <= set(Model.model_fields)


def test_to_model_unknown_include_raises():
    with pytest.raises(ValueError, match='unknown fields'):
        _MapsListingExtract.to_model(BaseModel, include={'nope'})


def test_to_model_envelope_collision_raises():
    """An envelope field colliding with a contract field is ambiguous -> raise."""
    with pytest.raises(ValueError, match='collide'):
        _MapsListingExtract.to_model(BaseModel, name='MapsCollide', name_field=(str, ...), phone=(str, ...))


def test_to_model_projects_onto_custom_base():
    """Field projection works onto an arbitrary caller-injected base (ODM stand-in)."""

    class _OdmBase(BaseModel):
        """Stand-in for beanie.Document / a Ninja Schema — caller owns the import."""

        _id: str | None = None

    Model = _MapsListingExtract.to_model(_OdmBase, name='MapsOdm', run_id=(str, ...))
    assert issubclass(Model, _OdmBase)
    inst = Model(name='Y', rating='3', phone='2', run_id='r2')
    assert inst.run_id == 'r2'

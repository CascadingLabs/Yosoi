"""Unit tests for yosoi.utils.signatures."""

from __future__ import annotations

from pydantic import Field

from yosoi.models.contract import Contract
from yosoi.utils.signatures import (
    SIGNATURE_SCHEME_VERSION,
    contract_signature,
    field_signature,
    signature_scheme_of,
)

# ---------------------------------------------------------------------------
# field_signature
# ---------------------------------------------------------------------------


def test_field_signature_determinism():
    sig1 = field_signature('title', 'Article headline', None)
    sig2 = field_signature('title', 'Article headline', None)
    assert sig1 == sig2


def test_field_signature_length():
    sig = field_signature('price', 'Product price', 'price')
    assert len(sig) == 16


def test_field_signature_normalizes_whitespace():
    sig1 = field_signature('title', 'Article  headline', None)
    sig2 = field_signature('title', 'Article headline', None)
    assert sig1 == sig2


def test_field_signature_normalizes_case():
    sig1 = field_signature('Title', 'Article Headline', None)
    sig2 = field_signature('title', 'article headline', None)
    assert sig1 == sig2


def test_field_signature_differs_on_different_fields():
    sig1 = field_signature('title', 'The title', None)
    sig2 = field_signature('price', 'The price', None)
    assert sig1 != sig2


def test_field_signature_differs_on_different_descriptions():
    sig1 = field_signature('title', 'Article headline', None)
    sig2 = field_signature('title', 'Product name', None)
    assert sig1 != sig2


def test_field_signature_differs_on_yosoi_type():
    sig1 = field_signature('price', 'The price', 'price')
    sig2 = field_signature('price', 'The price', None)
    assert sig1 != sig2


# ---------------------------------------------------------------------------
# contract_signature
# ---------------------------------------------------------------------------


class _SimpleContract(Contract):
    title: str = Field(description='Article title')
    author: str = Field(description='Author name')


class _AltContract(Contract):
    headline: str = Field(description='Article title')  # structural change: different field NAME
    author: str = Field(description='Author name')


def test_contract_signature_determinism():
    assert contract_signature(_SimpleContract) == contract_signature(_SimpleContract)


def test_contract_signature_is_scheme_versioned():
    sig = contract_signature(_SimpleContract)
    scheme, sep, digest = sig.partition(':')
    assert sep == ':'
    assert scheme == SIGNATURE_SCHEME_VERSION
    assert len(digest) == 16


def test_contract_signature_ignores_field_description() -> None:
    # v3: per-field description is advisory (no teeth) → two contracts identical in name, doc, and
    # field (name, yosoi_type) but differing ONLY in field prose get the SAME signature. Rewording a
    # description must never bust the selector cache. create_model gives them an identical __name__.
    from pydantic import create_model

    a = create_model('SameName', __base__=Contract, title=(str, Field(description='Article headline')))
    b = create_model('SameName', __base__=Contract, title=(str, Field(description='totally reworded prose')))
    assert contract_signature(a) == contract_signature(b)


def test_contract_signature_differs_on_field_change():
    sig1 = contract_signature(_SimpleContract)
    sig2 = contract_signature(_AltContract)
    assert sig1 != sig2


# ---------------------------------------------------------------------------
# W5 NOTE #2 — docstring + name disambiguation
# ---------------------------------------------------------------------------


class _Link(Contract):
    """A link."""

    url: str = Field(description='The link URL')
    title: str = Field(description='The link text')


class _OrganicLink(Contract):
    """A free/organic search result link."""

    url: str = Field(description='The link URL')
    title: str = Field(description='The link text')


class _AdLink(Contract):
    """A paid/sponsored result link."""

    url: str = Field(description='The link URL')
    title: str = Field(description='The link text')


def test_same_shape_contracts_differing_only_by_docstring_get_distinct_signatures():
    """Two contracts with identical fields but different docstrings must NOT collide.

    Regression for the nimbal serp_contracts.py clobber: AdLink vs OrganicLink
    shared one cache slot because the old signature ignored the docstring.
    """
    organic = contract_signature(_OrganicLink)
    ad = contract_signature(_AdLink)
    assert organic != ad
    # ... and both differ from the un-disambiguated base.
    assert contract_signature(_Link) != organic
    assert contract_signature(_Link) != ad


def test_signature_folds_in_class_name():
    """Two identically-documented but differently-named contracts also split."""

    class _A(Contract):
        """Same doc."""

        url: str = Field(description='u')

    class _B(Contract):
        """Same doc."""

        url: str = Field(description='u')

    assert contract_signature(_A) != contract_signature(_B)


def test_signature_scheme_of_extracts_prefix():
    assert signature_scheme_of(contract_signature(_SimpleContract)) == SIGNATURE_SCHEME_VERSION
    # A legacy un-prefixed signature reports v1.
    assert signature_scheme_of('abc123def4567890') == 'v1'

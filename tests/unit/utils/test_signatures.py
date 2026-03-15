"""Unit tests for yosoi.utils.signatures."""

from __future__ import annotations

from pydantic import Field

from yosoi.models.contract import Contract
from yosoi.utils.signatures import contract_signature, field_signature

# ---------------------------------------------------------------------------
# field_signature
# ---------------------------------------------------------------------------


def test_field_signature_determinism():
    sig1 = field_signature('title', 'Article headline', None, None)
    sig2 = field_signature('title', 'Article headline', None, None)
    assert sig1 == sig2


def test_field_signature_length():
    sig = field_signature('price', 'Product price', 'look for £ or $', 'price')
    assert len(sig) == 16


def test_field_signature_normalizes_whitespace():
    sig1 = field_signature('title', 'Article  headline', None, None)
    sig2 = field_signature('title', 'Article headline', None, None)
    assert sig1 == sig2


def test_field_signature_normalizes_case():
    sig1 = field_signature('Title', 'Article Headline', None, None)
    sig2 = field_signature('title', 'article headline', None, None)
    assert sig1 == sig2


def test_field_signature_differs_on_different_fields():
    sig1 = field_signature('title', 'The title', None, None)
    sig2 = field_signature('price', 'The price', None, None)
    assert sig1 != sig2


def test_field_signature_differs_on_different_descriptions():
    sig1 = field_signature('title', 'Article headline', None, None)
    sig2 = field_signature('title', 'Product name', None, None)
    assert sig1 != sig2


def test_field_signature_differs_on_hint():
    sig1 = field_signature('title', 'Headline', 'look in h1', None)
    sig2 = field_signature('title', 'Headline', None, None)
    assert sig1 != sig2


def test_field_signature_differs_on_yosoi_type():
    sig1 = field_signature('price', 'The price', None, 'price')
    sig2 = field_signature('price', 'The price', None, None)
    assert sig1 != sig2


# ---------------------------------------------------------------------------
# contract_signature
# ---------------------------------------------------------------------------


class _SimpleContract(Contract):
    title: str = Field(description='Article title')
    author: str = Field(description='Author name')


class _AltContract(Contract):
    title: str = Field(description='Different description')
    author: str = Field(description='Author name')


def test_contract_signature_determinism():
    assert contract_signature(_SimpleContract) == contract_signature(_SimpleContract)


def test_contract_signature_length():
    sig = contract_signature(_SimpleContract)
    assert len(sig) == 16


def test_contract_signature_differs_on_field_change():
    sig1 = contract_signature(_SimpleContract)
    sig2 = contract_signature(_AltContract)
    assert sig1 != sig2

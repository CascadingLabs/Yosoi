"""Tests for list[T] field support in contracts."""

import pytest

import yosoi as ys
from yosoi.models.contract import Contract, _unwrap_list_annotation

# ---------------------------------------------------------------------------
# _unwrap_list_annotation
# ---------------------------------------------------------------------------


def test_unwrap_list_str():
    assert _unwrap_list_annotation(list[str]) is str


def test_unwrap_list_float():
    assert _unwrap_list_annotation(list[float]) is float


def test_unwrap_plain_str():
    assert _unwrap_list_annotation(str) is None


def test_unwrap_plain_int():
    assert _unwrap_list_annotation(int) is None


def test_unwrap_bare_list():
    assert _unwrap_list_annotation(list) is None


# ---------------------------------------------------------------------------
# Contract.list_fields()
# ---------------------------------------------------------------------------


class AuthorsContract(Contract):
    title: str = ys.Title()
    authors: list[str] = ys.Field(description='List of authors')
    prices: list[float] = ys.Price()


def test_list_fields_returns_inner_types():
    result = AuthorsContract.list_fields()
    assert result == {'authors': str, 'prices': float}


def test_list_fields_excludes_scalars():
    result = AuthorsContract.list_fields()
    assert 'title' not in result


def test_list_fields_excludes_nested_contracts():
    class Inner(Contract):
        name: str

    class Outer(Contract):
        child: Inner
        tags: list[str] = ys.Field(description='tags')

    result = Outer.list_fields()
    assert 'child' not in result
    assert result == {'tags': str}


# ---------------------------------------------------------------------------
# field_descriptions() appends list hint
# ---------------------------------------------------------------------------


def test_field_descriptions_appends_list_hint():
    descs = AuthorsContract.field_descriptions()
    assert 'multiple expected' in descs['authors']
    assert 'multiple expected' in descs['prices']
    assert 'multiple expected' not in descs['title']


# ---------------------------------------------------------------------------
# to_selector_model() includes list fields
# ---------------------------------------------------------------------------


def test_to_selector_model_includes_list_fields():
    SelectorModel = AuthorsContract.to_selector_model()
    fields = SelectorModel.model_fields
    assert 'authors' in fields
    assert 'prices' in fields
    assert 'title' in fields


# ---------------------------------------------------------------------------
# Collision detection treats list as flat (not nested)
# ---------------------------------------------------------------------------


def test_collision_detection_treats_list_as_flat():
    """list[str] field should not trigger nested collision detection."""

    # This should not raise — authors_name is a flat field, not a nested expansion
    class NoCollision(Contract):
        authors: list[str] = ys.Field(description='authors')
        authors_name: str = ys.Field(description='author name')

    assert 'authors' in NoCollision.model_fields
    assert 'authors_name' in NoCollision.model_fields


# ---------------------------------------------------------------------------
# list[Contract] rejected at definition time
# ---------------------------------------------------------------------------


def test_list_contract_rejected_at_definition_time():
    """list[Contract] should raise TypeError — not yet supported."""

    class Inner(Contract):
        name: str

    with pytest.raises(TypeError, match='list\\[Inner\\] which is not yet supported'):

        class Bad(Contract):
            items: list[Inner] = ys.Field(description='nested list')

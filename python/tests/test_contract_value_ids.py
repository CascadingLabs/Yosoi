"""Public Contract value identities agree with the compiled field schema."""

from typing import Any, ClassVar

import pytest
from pydantic import ConfigDict, ValidationError

import yosoi as ys
from yosoi.contracts import ContractValue, FieldSchema, value_type_id


def test_value_type_ids_match_contract_schema_fields():
    class Product(ys.Contract):
        title: str = ys.Field("Product title", locator=ys.css("h1"))
        price: ys.Money = ys.Field("Price in USD", locator=ys.css(".price"))

    fields = {
        str(field.id): field.value_type for field in Product.contract_schema().fields
    }
    assert fields["title"] == value_type_id(str)
    assert fields["price"] == value_type_id(ys.Money) == ys.Money.TYPE_ID
    assert ys.Money.TYPE_ID == "money.usd"


def test_custom_contract_value_protocol_supplies_schema_identity_only():
    class CustomScalar(str):
        TYPE_ID: ClassVar[str] = "fixture.scalar"

    scalar_type: type[ContractValue] = CustomScalar
    assert value_type_id(scalar_type) == "fixture.scalar"

    field = FieldSchema(
        id="custom",
        description="Custom scalar identity",
        cardinality="exactly_one",
        value_type=value_type_id(CustomScalar),
    )
    assert field.value_type == "fixture.scalar"

    class CustomContract(ys.Contract):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        value: CustomScalar = ys.Field("Custom scalar", locator=ys.css(".custom"))

    with pytest.raises(ys._native.ContractError, match="Rust Contracts support"):
        CustomContract.contract_schema()


def test_custom_contract_value_type_id_shape_is_checked_but_empty_id_is_rust_checked():
    class MissingTypeId:
        pass

    class NonStringTypeId:
        TYPE_ID: ClassVar[int] = 7

    class EmptyTypeId:
        TYPE_ID: ClassVar[str] = ""

    class InstanceTypeId:
        TYPE_ID: ClassVar[str] = "fixture.instance"

    unsupported: Any = int
    missing: Any = MissingTypeId
    non_string: Any = NonStringTypeId
    instance: Any = InstanceTypeId()
    with pytest.raises(TypeError):
        value_type_id(unsupported)
    with pytest.raises(TypeError):
        value_type_id(missing)
    with pytest.raises(TypeError):
        value_type_id(non_string)
    with pytest.raises(TypeError):
        value_type_id(instance)

    assert value_type_id(EmptyTypeId) == ""
    with pytest.raises((ys._native.ContractError, ValidationError)):
        FieldSchema(
            id="empty_type",
            description="An empty scalar identity",
            cardinality="exactly_one",
            value_type=value_type_id(EmptyTypeId),
        )

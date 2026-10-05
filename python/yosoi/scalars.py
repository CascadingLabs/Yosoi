"""Validated Python values for the public Rust SDK's scalar newtypes."""

from __future__ import annotations

import json
from typing import Any, ClassVar, Self, cast

from pydantic_core import core_schema

from . import _native

RUST_DOMAIN_VALIDATED = object()


def _domain_value(kind: str, value: str | int) -> str | int:
    return json.loads(
        _native.validate_domain_model(kind, json.dumps(value, separators=(",", ":")))
    )


def _serialize_string(value: str) -> str:
    return str(value)


def _serialize_integer(value: int) -> int:
    return int(value)


class ValidatedString(str):
    """String scalar constructed and checked by its Rust SDK type."""

    _kind: ClassVar[str]

    def __new__(cls, value: str) -> Self:
        normalized = _domain_value(cls._kind, value)
        return str.__new__(cls, cast(str, normalized))

    @classmethod
    def try_new(cls, value: str) -> Self:
        return cls(value)

    def as_str(self) -> str:
        return str(self)

    @classmethod
    def _pydantic_validate(cls, value: str) -> Self:
        try:
            return cls(value)
        except Exception as error:
            raise ValueError(str(error)) from error

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: Any
    ) -> core_schema.CoreSchema:
        del source, handler

        def validate(value: str, info: Any) -> Self:
            if info.context is RUST_DOMAIN_VALIDATED:
                return str.__new__(cls, value)
            return cls._pydantic_validate(value)

        return core_schema.with_info_after_validator_function(
            validate,
            core_schema.str_schema(strict=True),
            serialization=core_schema.plain_serializer_function_ser_schema(
                _serialize_string,
                return_schema=core_schema.str_schema(),
            ),
        )


class ValidatedInteger(int):
    """Integer scalar with the width and constructor rules of its Rust type."""

    _kind: ClassVar[str]

    def __new__(cls, value: int) -> Self:
        normalized = _domain_value(cls._kind, value)
        return int.__new__(cls, cast(int, normalized))

    @classmethod
    def try_new(cls, value: int) -> Self:
        return cls(value)

    def get(self) -> int:
        return int(self)

    @classmethod
    def _pydantic_validate(cls, value: int) -> Self:
        try:
            return cls(value)
        except Exception as error:
            raise ValueError(str(error)) from error

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: Any
    ) -> core_schema.CoreSchema:
        del source, handler

        def validate(value: int, info: Any) -> Self:
            if info.context is RUST_DOMAIN_VALIDATED:
                return int.__new__(cls, value)
            return cls._pydantic_validate(value)

        return core_schema.with_info_after_validator_function(
            validate,
            core_schema.int_schema(strict=True),
            serialization=core_schema.plain_serializer_function_ser_schema(
                _serialize_integer,
                return_schema=core_schema.int_schema(),
            ),
        )


class DocumentId(ValidatedString):
    _kind = "document_id"


class ContractId(ValidatedString):
    _kind = "contract_id"


class FieldId(ValidatedString):
    _kind = "field_id"


class OutputId(ValidatedString):
    _kind = "output_id"


class RegionId(ValidatedString):
    _kind = "region_id"


class JsonCoordinate(ValidatedString):
    _kind = "json_coordinate"

    def as_pointer(self) -> str:
        return str(self)


class DocumentEpoch(ValidatedInteger):
    _kind = "document_epoch"


class DomNodeId(ValidatedInteger):
    _kind = "dom_node_id"


class CountLimit(ValidatedInteger):
    _kind = "count_limit"


class StepLimit(ValidatedInteger):
    _kind = "step_limit"


class AddressableByteLimit(ValidatedInteger):
    _kind = "addressable_byte_limit"

    def as_usize(self) -> int:
        return self.get()


class EventLimit(ValidatedInteger):
    _kind = "event_limit"

    def as_usize(self) -> int:
        return self.get()


class ResourceLimit(ValidatedInteger):
    _kind = "resource_limit"


class AccessibilityNodeLimit(ValidatedInteger):
    _kind = "accessibility_node_limit"


class MaximumElapsed(ValidatedInteger):
    _kind = "maximum_elapsed"

    def as_microseconds(self) -> int:
        return self.get()


class RedirectHopLimit(ValidatedInteger):
    _kind = "redirect_hop_limit"


class Budget(ValidatedInteger):
    _kind = "budget"


class ProviderDefaultsVersion(ValidatedInteger):
    _kind = "provider_defaults_version"

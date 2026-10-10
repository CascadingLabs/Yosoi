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


class _RustUnsignedResult(int):
    """Typed wrapper for an unsigned value returned by a Rust conversion."""

    def __new__(cls, value: int) -> Self:
        del value
        raise TypeError(f"{cls.__name__} values come from Rust SDK conversions")

    @classmethod
    def _from_rust(cls, value: int) -> Self:
        return int.__new__(cls, value)

    def get(self) -> int:
        return int(self)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({int(self)})"


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

    def to_byte_limit(self) -> ByteLimit:
        """Convert to a positive byte limit; the value is measured in bytes."""
        value = _native.validate_domain_model(
            "addressable_byte_limit_to_byte_limit",
            json.dumps(self.get(), separators=(",", ":")),
        )
        return ByteLimit._from_rust(cast(int, json.loads(value)))


class EventLimit(ValidatedInteger):
    _kind = "event_limit"

    @classmethod
    def default(cls) -> Self:
        return cls(cast(int, _domain_value("event_limit_default", 0)))

    def as_usize(self) -> int:
        return self.get()


class ResourceLimit(ValidatedInteger):
    _kind = "resource_limit"

    def to_nonzero(self) -> NonZeroU32:
        """Return the corresponding positive 32-bit resource bound."""
        value = _native.validate_domain_model(
            "resource_limit_to_nonzero",
            json.dumps(self.get(), separators=(",", ":")),
        )
        return NonZeroU32._from_rust(cast(int, json.loads(value)))


class AccessibilityNodeLimit(ValidatedInteger):
    _kind = "accessibility_node_limit"

    def to_nonzero(self) -> NonZeroU32:
        """Return the corresponding positive 32-bit accessibility-node bound."""
        value = _native.validate_domain_model(
            "accessibility_node_limit_to_nonzero",
            json.dumps(self.get(), separators=(",", ":")),
        )
        return NonZeroU32._from_rust(cast(int, json.loads(value)))


class MaximumElapsed(ValidatedInteger):
    _kind = "maximum_elapsed"

    @classmethod
    def default(cls) -> Self:
        return cls(cast(int, _domain_value("maximum_elapsed_default", 0)))

    def as_microseconds(self) -> int:
        return self.get()

    def to_capture_deadline(self) -> CaptureDeadline:
        """Convert the positive elapsed limit to a microsecond deadline."""
        value = _native.validate_domain_model(
            "maximum_elapsed_to_capture_deadline",
            json.dumps(self.get(), separators=(",", ":")),
        )
        return CaptureDeadline._from_rust(cast(int, json.loads(value)))


class RedirectHopLimit(ValidatedInteger):
    _kind = "redirect_hop_limit"

    @classmethod
    def default(cls) -> Self:
        return cls(cast(int, _domain_value("redirect_hop_limit_default", 0)))


class Budget(ValidatedInteger):
    _kind = "budget"


class ProviderDefaultsVersion(ValidatedInteger):
    _kind = "provider_defaults_version"


class NonZeroU32(_RustUnsignedResult):
    """Positive 32-bit value returned by Rust policy conversions."""


class ByteLimit(_RustUnsignedResult):
    """Positive byte limit returned by a policy conversion; units are bytes."""

    def as_usize(self) -> int:
        # This value comes from AddressableByteLimit, which checks platform size.
        return self.get()


class CaptureDeadline(_RustUnsignedResult):
    """Positive capture deadline represented in microseconds."""

    def as_microseconds(self) -> int:
        return self.get()

    def duration(self) -> CaptureDuration:
        value = _native.validate_domain_model(
            "maximum_elapsed_capture_duration",
            json.dumps(self.get(), separators=(",", ":")),
        )
        return CaptureDuration._from_rust(cast(int, json.loads(value)))


class CaptureDuration(_RustUnsignedResult):
    """Elapsed duration represented in microseconds."""

    def as_microseconds(self) -> int:
        return self.get()

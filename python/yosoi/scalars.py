"""Validated Python values for the public Rust SDK's scalar newtypes."""

from __future__ import annotations

import json
from typing import Any, ClassVar, Self, cast

from pydantic_core import core_schema

from . import _native

RUST_DOMAIN_VALIDATED = object()
"""Internal reconstruction context for data already checked by Rust.

Pydantic domain validators use this marker to avoid repeating native checks.
It does not validate caller input or create ownership of native resources.
"""


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
        """Construct a domain-specific string scalar using Rust validation.

        Args:
            value: Authored string accepted by the selected SDK scalar constructor.

        Returns:
            Immutable validated text without acquiring external data.

        Raises:
            YosoiError: The domain-specific native constructor rejects the input.
        """
        normalized = _domain_value(cls._kind, value)
        return str.__new__(cls, cast(str, normalized))

    @classmethod
    def try_new(cls, value: str) -> Self:
        """Validate text using the domain-specific subclass constructor.

        Args:
            value: Authored string to validate in Rust.

        Returns:
            An immutable instance of the selected string scalar subclass.

        Raises:
            YosoiError: The selected domain rejects the supplied string.
        """
        return cls(value)

    def as_str(self) -> str:
        """Return the validated retained spelling as an ordinary Python string."""
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
        """Provide strict string validation and serialization for Pydantic fields."""
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
        """Construct a domain-specific integer using Rust width and value checks.

        Args:
            value: Authored integer in the selected scalar domain and units.

        Returns:
            Immutable numeric value without changing its domain-specific units.

        Raises:
            YosoiError: Native width, positivity, or addressability checks reject input.
        """
        normalized = _domain_value(cls._kind, value)
        return int.__new__(cls, cast(int, normalized))

    @classmethod
    def try_new(cls, value: int) -> Self:
        """Validate an integer using the domain-specific subclass constructor.

        Args:
            value: Authored integer in the selected scalar's units.

        Returns:
            An immutable scalar checked by its Rust constructor.

        Raises:
            YosoiError: The selected domain rejects the width or value.
        """
        return cls(value)

    def get(self) -> int:
        """Return the retained numeric value without converting its units."""
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
        """Provide strict integer validation and serialization for Pydantic fields."""
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
        """Reject direct construction of values reserved for Rust conversions.

        Args:
            value: Ignored attempted constructor input.

        Raises:
            TypeError: Conversion-result wrappers are created only by SDK conversions.
        """
        del value
        raise TypeError(f"{cls.__name__} values come from Rust SDK conversions")

    @classmethod
    def _from_rust(cls, value: int) -> Self:
        return int.__new__(cls, value)

    def get(self) -> int:
        """Return the converted unsigned value without changing its units."""
        return int(self)

    def __repr__(self) -> str:
        """Return the scalar result type and numeric value for inspection."""
        return f"{type(self).__name__}({int(self)})"


class DocumentId(ValidatedString):
    """Authored nonblank document identity, independent of an acquisition URL."""
    _kind = "document_id"


class ContractId(ValidatedString):
    """Authored nonblank identity distinguishing portable Contract schemas."""
    _kind = "contract_id"


class FieldId(ValidatedString):
    """Authored nonblank field identity matching Contract output evidence."""
    _kind = "field_id"


class OutputId(ValidatedString):
    """Authored nonblank locator-output identity for ordered findings."""
    _kind = "output_id"


class RegionId(ValidatedString):
    """Authored nonblank repeated-region identity for finding lineage."""
    _kind = "region_id"


class JsonCoordinate(ValidatedString):
    """Validated JSON Pointer spelling without checking document resolution."""
    _kind = "json_coordinate"

    def as_pointer(self) -> str:
        """Return validated pointer spelling; the empty pointer denotes the root."""
        return str(self)


class DocumentEpoch(ValidatedInteger):
    """Positive u64 document-local generation for DOM and accessibility snapshots."""
    _kind = "document_epoch"


class DomNodeId(ValidatedInteger):
    """Positive u64 node identity meaningful only within its snapshot epoch."""
    _kind = "dom_node_id"


class CountLimit(ValidatedInteger):
    """Positive u64 document or locator count; zero does not mean unlimited."""
    _kind = "count_limit"


class StepLimit(ValidatedInteger):
    """Positive u32 locator step count; zero does not mean unlimited."""
    _kind = "step_limit"


class AddressableByteLimit(ValidatedInteger):
    """Positive u64 byte bound that also fits the Rust platform address size."""
    _kind = "addressable_byte_limit"

    def as_usize(self) -> int:
        """Return the byte bound already checked to fit Rust platform address size."""
        return self.get()

    def to_byte_limit(self) -> ByteLimit:
        """Convert to a positive byte limit; the value is measured in bytes."""
        value = _native.validate_domain_model(
            "addressable_byte_limit_to_byte_limit",
            json.dumps(self.get(), separators=(",", ":")),
        )
        return ByteLimit._from_rust(cast(int, json.loads(value)))


class EventLimit(ValidatedInteger):
    """Positive addressable u64 count of admitted browser capture events."""
    _kind = "event_limit"

    @classmethod
    def default(cls) -> Self:
        """Return the browser event count selected by the Rust package default."""
        return cls(cast(int, _domain_value("event_limit_default", 0)))

    def as_usize(self) -> int:
        """Return the event count already checked for platform addressability."""
        return self.get()


class ResourceLimit(ValidatedInteger):
    """Positive addressable u32 count of browser resources admitted to a capture."""
    _kind = "resource_limit"

    def to_nonzero(self) -> NonZeroU32:
        """Return the corresponding positive 32-bit resource bound."""
        value = _native.validate_domain_model(
            "resource_limit_to_nonzero",
            json.dumps(self.get(), separators=(",", ":")),
        )
        return NonZeroU32._from_rust(cast(int, json.loads(value)))


class AccessibilityNodeLimit(ValidatedInteger):
    """Positive addressable u32 bound on accessibility snapshot nodes."""
    _kind = "accessibility_node_limit"

    def to_nonzero(self) -> NonZeroU32:
        """Return the corresponding positive 32-bit accessibility-node bound."""
        value = _native.validate_domain_model(
            "accessibility_node_limit_to_nonzero",
            json.dumps(self.get(), separators=(",", ":")),
        )
        return NonZeroU32._from_rust(cast(int, json.loads(value)))


class MaximumElapsed(ValidatedInteger):
    """Positive u64 elapsed budget measured in microseconds, not a timestamp."""
    _kind = "maximum_elapsed"

    @classmethod
    def default(cls) -> Self:
        """Return the Rust default elapsed budget in microseconds."""
        return cls(cast(int, _domain_value("maximum_elapsed_default", 0)))

    def as_microseconds(self) -> int:
        """Return the elapsed budget in microseconds without creating a deadline."""
        return self.get()

    def to_capture_deadline(self) -> CaptureDeadline:
        """Convert the positive elapsed limit to a microsecond deadline."""
        value = _native.validate_domain_model(
            "maximum_elapsed_to_capture_deadline",
            json.dumps(self.get(), separators=(",", ":")),
        )
        return CaptureDeadline._from_rust(cast(int, json.loads(value)))


class RedirectHopLimit(ValidatedInteger):
    """Positive u32 bound on Direct HTTP redirect transitions."""
    _kind = "redirect_hop_limit"

    @classmethod
    def default(cls) -> Self:
        """Return the positive redirect-hop bound selected by Rust defaults."""
        return cls(cast(int, _domain_value("redirect_hop_limit_default", 0)))


class Budget(ValidatedInteger):
    """Positive u32 Map discovery budget; zero never means unlimited."""
    _kind = "budget"


class ProviderDefaultsVersion(ValidatedInteger):
    """Positive u16 version selecting certified provider-default metadata."""
    _kind = "provider_defaults_version"


class NonZeroU32(_RustUnsignedResult):
    """Positive 32-bit value returned by Rust policy conversions."""


class ByteLimit(_RustUnsignedResult):
    """Positive byte limit returned by a policy conversion; units are bytes."""

    def as_usize(self) -> int:
        # This value comes from AddressableByteLimit, which checks platform size.
        """Return converted bytes already checked for platform addressability."""
        return self.get()


class CaptureDeadline(_RustUnsignedResult):
    """Positive capture deadline represented in microseconds."""

    def as_microseconds(self) -> int:
        """Return the positive elapsed bound in microseconds, not a timestamp."""
        return self.get()

    def duration(self) -> CaptureDuration:
        """Convert the microsecond capture bound to a typed duration value.

        Returns:
            A Rust-produced duration preserving the exact microsecond units.

        Raises:
            ValueError: Native capture-duration conversion cannot represent the value.
        """
        value = _native.validate_domain_model(
            "maximum_elapsed_capture_duration",
            json.dumps(self.get(), separators=(",", ":")),
        )
        return CaptureDuration._from_rust(cast(int, json.loads(value)))


class CaptureDuration(_RustUnsignedResult):
    """Elapsed duration represented in microseconds."""

    def as_microseconds(self) -> int:
        """Return the converted elapsed duration in microseconds."""
        return self.get()

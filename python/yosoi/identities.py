"""Public activity/capture identities backed by Rust generation and parsing."""

from __future__ import annotations

from typing import Self

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

from . import _native


class ActivityId(str):
    """Canonical random UUID v4 identity for one activity occurrence.

    Parsing validates lowercase hyphenated RFC 4122 UUID v4 text in Rust; it
    does not establish that an activity exists in an archive. As a string value,
    the identity is immutable and can be serialized without native object state.
    """

    def __new__(cls, value: str) -> Self:
        """Validate canonical UUID v4 text and create an immutable identity.

        Args:
            value: Lowercase hyphenated UUID v4 representation.

        Raises:
            RequestError: The text is invalid, noncanonical, or not RFC 4122 v4.
        """
        return str.__new__(cls, _native.activity_identity(value, False))

    @classmethod
    def random(cls) -> Self:
        """Generate a fresh UUID v4 in Rust without creating an archived activity."""
        return cls(_native.activity_identity(None, False))

    @classmethod
    def from_str(cls, value: str) -> Self:
        """Parse canonical text using the subclass constructor's validation.

        Args:
            value: Lowercase hyphenated UUID v4 representation.

        Returns:
            An immutable identity of the requested subclass.

        Raises:
            RequestError: The text is invalid, noncanonical, or not RFC 4122 v4.
        """
        return cls(value)

    def as_bytes(self) -> bytes:
        """Return the 16 UUID bytes in network byte order as an owned value."""
        return bytes(_native.activity_identity_bytes(self))

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: object, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        """Validate strict string inputs in Rust and serialize as canonical text."""
        return core_schema.no_info_after_validator_function(
            cls,
            core_schema.str_schema(strict=True),
            serialization=core_schema.to_string_ser_schema(),
        )


class CaptureId(ActivityId):
    """An activity identity designated as a capture by its Python type.

    The type preserves capture-specific authoring vocabulary. Parsing a UUID
    does not verify the existence or contents of a corresponding capture.
    """

    def __new__(cls, value: str) -> Self:
        """Parse canonical UUID v4 text as a capture identity.

        Args:
            value: Lowercase hyphenated UUID v4 representation.

        Raises:
            RequestError: The text is invalid, noncanonical, or not RFC 4122 v4.
        """
        return str.__new__(cls, _native.activity_identity(value, True))

    @classmethod
    def random(cls) -> Self:
        """Generate a fresh capture identity without acquiring or archiving content."""
        return cls(_native.activity_identity(None, True))

    def activity_id(self) -> ActivityId:
        """Return the same UUID represented as the general activity type."""
        return ActivityId(self)


class RequestId(ActivityId):
    """A validated activity UUID used to correlate one authored request.

    The Python type distinguishes request vocabulary without changing UUID
    encoding or checking whether the request has executed.
    """

    def activity_id(self) -> ActivityId:
        """Return the same request UUID represented as a general activity identity."""
        return ActivityId(self)


class ContractIdentity(str):
    """The hexadecimal representation of a Rust-computed 32-byte identity."""

    def __new__(cls, value: str) -> Self:
        """Create an immutable identity from canonical lowercase hexadecimal text.

        Args:
            value: Exactly 64 lowercase hex digits encoding 32 bytes.

        Raises:
            ValueError: The input is not canonical 32-byte lowercase hex.
        """
        decoded = bytes.fromhex(value)
        if len(decoded) != 32 or decoded.hex() != value:
            raise ValueError(
                "Contract identity must be canonical 32-byte lowercase hex"
            )
        return str.__new__(cls, value)

    def as_bytes(self) -> bytes:
        """Decode the identity into an owned 32-byte value without recomputing it."""
        return bytes.fromhex(self)

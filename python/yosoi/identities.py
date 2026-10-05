"""Public activity/capture identities backed by Rust generation and parsing."""

from __future__ import annotations

from typing import Self

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

from . import _native


class ActivityId(str):
    def __new__(cls, value: str) -> Self:
        return str.__new__(cls, _native.activity_identity(value, False))

    @classmethod
    def random(cls) -> Self:
        return cls(_native.activity_identity(None, False))

    @classmethod
    def from_str(cls, value: str) -> Self:
        return cls(value)

    def as_bytes(self) -> bytes:
        return bytes(_native.activity_identity_bytes(self))

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: object, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls,
            core_schema.str_schema(strict=True),
            serialization=core_schema.to_string_ser_schema(),
        )


class CaptureId(ActivityId):
    def __new__(cls, value: str) -> Self:
        return str.__new__(cls, _native.activity_identity(value, True))

    @classmethod
    def random(cls) -> Self:
        return cls(_native.activity_identity(None, True))

    def activity_id(self) -> ActivityId:
        return ActivityId(self)


class RequestId(ActivityId):
    def activity_id(self) -> ActivityId:
        return ActivityId(self)


class ContractIdentity(str):
    """The hexadecimal representation of a Rust-computed 32-byte identity."""

    def __new__(cls, value: str) -> Self:
        decoded = bytes.fromhex(value)
        if len(decoded) != 32 or decoded.hex() != value:
            raise ValueError(
                "Contract identity must be canonical 32-byte lowercase hex"
            )
        return str.__new__(cls, value)

    def as_bytes(self) -> bytes:
        return bytes.fromhex(self)

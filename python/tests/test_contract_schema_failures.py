"""Public Python adapters for Rust ContractSchemaError outcome payloads."""

from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from yosoi.contracts import (
    ContractSchemaFailure,
    RuntimeExtractionFailure,
    RuntimeValidationFailure,
)


@pytest.mark.parametrize(
    "failure_type",
    [RuntimeExtractionFailure, RuntimeValidationFailure],
)
def test_invalid_schema_failure_adapter_keeps_typed_rust_error(
    failure_type: Any,
) -> None:
    message = "contract field is duplicated: title"
    payload = {
        "kind": "invalid_contract_schema",
        "message": message,
        "schema_error": {
            "variant": "DuplicateField",
            "details": {"field": "title"},
        },
    }

    failure = TypeAdapter(failure_type).validate_python(payload)

    assert failure.kind == "invalid_contract_schema"
    assert failure.message == message
    assert failure.schema_error is not None
    assert failure.schema_error.variant == "DuplicateField"
    assert failure.schema_error.details.field == "title"
    assert failure.model_dump(mode="json") == payload


@pytest.mark.parametrize(
    "failure_type",
    [RuntimeExtractionFailure, RuntimeValidationFailure],
)
def test_invalid_schema_failure_adapter_accepts_legacy_message_only_shape(
    failure_type: Any,
) -> None:
    payload = {
        "kind": "invalid_contract_schema",
        "message": "contract schema version 2 is unsupported",
    }

    failure = TypeAdapter(failure_type).validate_python(payload)

    assert failure.schema_error is None
    assert failure.model_dump(mode="json") == payload


def test_contract_schema_failure_adapter_preserves_variant_payloads() -> None:
    adapter = TypeAdapter(ContractSchemaFailure)
    payload = {"variant": "UnsupportedVersion", "details": {"observed": 2}}

    failure = adapter.validate_python(payload)

    assert failure.variant == "UnsupportedVersion"
    assert failure.details.observed == 2
    assert adapter.dump_python(failure, mode="json") == payload


@pytest.mark.parametrize("bad_count", [-1, True, 1.5, 1 << 64])
def test_budget_failure_payloads_preserve_rust_unsigned_counts(bad_count: Any) -> None:
    for failure_type, kind, extras in (
        (RuntimeExtractionFailure, "limit_exceeded", {"limit": "candidates"}),
        (RuntimeValidationFailure, "record_limit_exceeded", {}),
    ):
        with pytest.raises(ValidationError):
            TypeAdapter(failure_type).validate_python(
                {
                    "kind": kind,
                    "maximum": bad_count,
                    "observed": 1,
                    **extras,
                }
            )

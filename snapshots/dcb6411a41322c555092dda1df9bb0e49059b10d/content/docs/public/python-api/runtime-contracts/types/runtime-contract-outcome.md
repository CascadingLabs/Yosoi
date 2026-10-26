---
title: "RuntimeContractOutcome"
description: "yosoi.runtime_contracts.RuntimeContractOutcome Python API reference."
order: 0
---

`yosoi.runtime_contracts.RuntimeContractOutcome`

```python
class RuntimeContractOutcome:
```

Inspect runtime validation results while retaining the Rust handle.

The Python view includes empty tuples for missing candidate fields. JSON
serialization preserves the original Rust wire, which may omit those entries.

Attributes:
    contract_schema: Schema used to interpret and complete candidate field mappings.
    view: Immutable status-tagged validation DTO with every schema field
        represented.

[Source: python/yosoi/runtime_contracts.py:869](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L869-L1012)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, contract_schema: ContractSchema, handle: _native.ContractOutcome) -> None:
```

Parse a native validation result and seal the Python view.

Args:
    contract_schema: Schema that supplies missing candidate field entries.
    handle: Rust validation result retained for subsequent operations.

Raises:
    ValueError: Native JSON does not match the expected outcome structure.

[Source: python/yosoi/runtime_contracts.py:883](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L883-L906)

### status

```python
@property
def status(self) -> str:
```

Return the wire status; it does not alone prove business success.

[Source: python/yosoi/runtime_contracts.py:915](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L915-L917)

### document_id

```python
@property
def document_id(self) -> str | None:
```

Return the source document identity when this status carries one.

[Source: python/yosoi/runtime_contracts.py:920](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L920-L922)

### completeness

```python
@property
def completeness(self) -> IncompleteEvidence | None:
```

Return incomplete-evidence details for an indeterminate result, else None.

[Source: python/yosoi/runtime_contracts.py:925](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L925-L927)

### reason_code

```python
@property
def reason_code(self) -> str | None:
```

Return the indeterminate reason code, or None for other statuses.

[Source: python/yosoi/runtime_contracts.py:930](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L930-L932)

### failure

```python
@property
def failure(self) -> Failure | RuntimeExtractionFailure | RuntimeValidationFailure | None:
```

Return the typed phase failure, or None when this status has no failure.

[Source: python/yosoi/runtime_contracts.py:935](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L935-L939)

### records

```python
@property
def records(self) -> tuple[RuntimeValidatedRecord, ...]:
```

Return accepted records for evaluated results, otherwise an empty tuple.

[Source: python/yosoi/runtime_contracts.py:942](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L942-L944)

### issues

```python
@property
def issues(self) -> tuple[RuntimeRecordIssue, ...]:
```

Return evaluated candidate issues, or an empty tuple otherwise.

[Source: python/yosoi/runtime_contracts.py:947](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L947-L949)

### extraction_diagnostics

```python
@property
def extraction_diagnostics(self) -> tuple[ExtractionDiagnostic, ...]:
```

Return evaluated extraction diagnostics, otherwise an empty tuple.

[Source: python/yosoi/runtime_contracts.py:952](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L952-L958)

### require_all

```python
def require_all(self) -> list[RuntimeValidatedRecord]:
```

Return records only when every candidate and extraction check passed.

Complete no-match returns an empty list. This method preserves the outcome
and never silently returns only the successful subset.

Returns:
    All accepted records as typed values with candidate evidence.

Raises:
    ContractIssues: Evidence is indeterminate, a phase failed or was rejected,
        or evaluated results contain field issues or extraction diagnostics.

[Source: python/yosoi/runtime_contracts.py:960](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L960-L982)

### to_archived

```python
def to_archived(self, schema: ContractSchema | None=None) -> ArchivedContractOutcome:
```

Convert this result to Rust's code-independent portable archive.

Args:
    schema: Archive schema; None uses this outcome's original Contract schema.

Returns:
    Typed archive with portable values and retained evidence.

Raises:
    ContractError: Rust rejects the schema or cannot archive the result.

[Source: python/yosoi/runtime_contracts.py:984](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L984-L1000)

### to_json

```python
def to_json(self) -> str:
```

Return the original Rust wire JSON without serializing the enriched view.

[Source: python/yosoi/runtime_contracts.py:1002](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L1002-L1004)

### model_dump

```python
def model_dump(self) -> dict[str, Any]:
```

Decode the original wire into a new dictionary.

[Source: python/yosoi/runtime_contracts.py:1006](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L1006-L1008)

### model_dump_json

```python
def model_dump_json(self) -> str:
```

Return the original Rust wire JSON without serializing the enriched view.

[Source: python/yosoi/runtime_contracts.py:1010](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L1010-L1012)

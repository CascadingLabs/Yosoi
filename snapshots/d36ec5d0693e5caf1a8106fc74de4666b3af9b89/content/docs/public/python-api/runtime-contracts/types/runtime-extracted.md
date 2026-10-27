---
title: "RuntimeExtracted"
description: "yosoi.runtime_contracts.RuntimeExtracted Python API reference."
order: 0
---

`yosoi.runtime_contracts.RuntimeExtracted`

```python
class RuntimeExtracted:
```

Inspect runtime extraction results while retaining the Rust handle.

The Python view includes empty tuples for missing candidate fields. JSON
serialization preserves the original Rust wire, which may omit those entries.

Attributes:
    contract_schema: Schema used to interpret and complete candidate field mappings.
    view: Immutable status-tagged extraction DTO with every schema field
        represented.

[Source: python/yosoi/runtime_contracts.py:754](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L754-L866)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, contract_schema: ContractSchema, handle: _native.Extracted) -> None:
```

Parse a native extraction result and seal the Python view.

Args:
    contract_schema: Schema that supplies missing candidate field entries.
    handle: Rust extraction result retained for subsequent operations.

Raises:
    ValueError: Native JSON does not match the expected outcome structure.

[Source: python/yosoi/runtime_contracts.py:768](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L768-L794)

### status

```python
@property
def status(self) -> str:
```

Return the wire status; it does not alone prove business success.

[Source: python/yosoi/runtime_contracts.py:803](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L803-L805)

### candidates

```python
@property
def candidates(self) -> tuple[RuntimeCandidate, ...]:
```

Return unvalidated candidates, or an empty tuple for other statuses.

[Source: python/yosoi/runtime_contracts.py:808](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L808-L810)

### diagnostics

```python
@property
def diagnostics(self) -> tuple[ExtractionDiagnostic, ...]:
```

Return candidate diagnostics, or an empty tuple for other statuses.

[Source: python/yosoi/runtime_contracts.py:813](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L813-L817)

### document_id

```python
@property
def document_id(self) -> str | None:
```

Return the source document identity when this status carries one.

[Source: python/yosoi/runtime_contracts.py:820](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L820-L822)

### completeness

```python
@property
def completeness(self) -> IncompleteEvidence | None:
```

Return incomplete-evidence details for an indeterminate result, else None.

[Source: python/yosoi/runtime_contracts.py:825](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L825-L827)

### reason_code

```python
@property
def reason_code(self) -> str | None:
```

Return the indeterminate reason code, or None for other statuses.

[Source: python/yosoi/runtime_contracts.py:830](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L830-L832)

### failure

```python
@property
def failure(self) -> Failure | RuntimeExtractionFailure | None:
```

Return the typed phase failure, or None when this status has no failure.

[Source: python/yosoi/runtime_contracts.py:835](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L835-L837)

### validate

```python
def validate(self, *, limits: ValidationLimits | None=None) -> RuntimeContractOutcome:
```

Validate extracted candidates in Rust without discarding this view.

Args:
    limits: Optional validation budgets; None uses Rust defaults.

Returns:
    Status-tagged outcome retaining accepted records and rejected candidates.
    Incomplete evidence and phase rejection remain explicit outcome variants.

[Source: python/yosoi/runtime_contracts.py:839](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L839-L854)

### to_json

```python
def to_json(self) -> str:
```

Return the original Rust wire JSON without serializing the enriched view.

[Source: python/yosoi/runtime_contracts.py:856](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L856-L858)

### model_dump

```python
def model_dump(self) -> dict[str, Any]:
```

Decode the original wire into a new dictionary.

[Source: python/yosoi/runtime_contracts.py:860](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L860-L862)

### model_dump_json

```python
def model_dump_json(self) -> str:
```

Return the original Rust wire JSON without serializing the enriched view.

[Source: python/yosoi/runtime_contracts.py:864](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L864-L866)

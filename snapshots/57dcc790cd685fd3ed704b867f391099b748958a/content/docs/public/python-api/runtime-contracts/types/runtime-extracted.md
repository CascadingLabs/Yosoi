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

[Source: python/yosoi/runtime_contracts.py:786](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L786-L898)

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

[Source: python/yosoi/runtime_contracts.py:800](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L800-L826)

### status

```python
@property
def status(self) -> str:
```

Return the wire status; it does not alone prove business success.

[Source: python/yosoi/runtime_contracts.py:835](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L835-L837)

### candidates

```python
@property
def candidates(self) -> tuple[RuntimeCandidate, ...]:
```

Return unvalidated candidates, or an empty tuple for other statuses.

[Source: python/yosoi/runtime_contracts.py:840](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L840-L842)

### diagnostics

```python
@property
def diagnostics(self) -> tuple[ExtractionDiagnostic, ...]:
```

Return candidate diagnostics, or an empty tuple for other statuses.

[Source: python/yosoi/runtime_contracts.py:845](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L845-L849)

### document_id

```python
@property
def document_id(self) -> str | None:
```

Return the source document identity when this status carries one.

[Source: python/yosoi/runtime_contracts.py:852](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L852-L854)

### completeness

```python
@property
def completeness(self) -> IncompleteEvidence | None:
```

Return incomplete-evidence details for an indeterminate result, else None.

[Source: python/yosoi/runtime_contracts.py:857](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L857-L859)

### reason_code

```python
@property
def reason_code(self) -> str | None:
```

Return the indeterminate reason code, or None for other statuses.

[Source: python/yosoi/runtime_contracts.py:862](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L862-L864)

### failure

```python
@property
def failure(self) -> Failure | RuntimeExtractionFailure | None:
```

Return the typed phase failure, or None when this status has no failure.

[Source: python/yosoi/runtime_contracts.py:867](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L867-L869)

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

[Source: python/yosoi/runtime_contracts.py:871](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L871-L886)

### to_json

```python
def to_json(self) -> str:
```

Return the original Rust wire JSON without serializing the enriched view.

[Source: python/yosoi/runtime_contracts.py:888](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L888-L890)

### model_dump

```python
def model_dump(self) -> dict[str, Any]:
```

Decode the original wire into a new dictionary.

[Source: python/yosoi/runtime_contracts.py:892](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L892-L894)

### model_dump_json

```python
def model_dump_json(self) -> str:
```

Return the original Rust wire JSON without serializing the enriched view.

[Source: python/yosoi/runtime_contracts.py:896](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L896-L898)

---
title: "Extracted"
description: "yosoi.contracts.Extracted Python API reference."
order: 0
---

`yosoi.contracts.Extracted`

```python
class Extracted[T: 'Contract'](_ReadOnlyView):
```

Read-only candidate assembly outcome awaiting explicit validation.

Attributes:
    contract: Typed record definition used for extraction.
    status: candidates, no_match, indeterminate, locate_failed, or rejected retains
        the phase distinction.
    document_id: Examined document identity when available.
    failure: Typed terminal location or extraction rejection when present.
    completeness: Partial or unknown coverage for indeterminate outcomes.
    reason_code: Structural explanation of indeterminate coverage.
    candidates: Grouped raw evidence, not accepted typed records.
    diagnostics: Nonfatal extraction issues such as incompatible lineage.

[Source: python/yosoi/contracts.py:756](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L756-L852)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, contract: type[T], handle: _native.Extracted) -> None:
```

Retain a native extraction handle and read-only evidence.

Args:
    contract: Typed definition used to interpret field identities.
    handle: Native extraction outcome from the Rust pipeline.

Construction does not validate candidate values or acquire documents.

[Source: python/yosoi/contracts.py:783](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L783-L829)

### validate

```python
def validate(self, *, limits: ValidationLimits | None=None) -> ContractOutcome[T]:
```

Convert and validate evidence with explicit or default budgets.

Args:
    limits: Validation budgets, or None for Rust defaults.

Returns:
    Accepted records, rejected candidates, or terminal states. Incomplete
    evidence is never converted into an empty successful result.

[Source: python/yosoi/contracts.py:831](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L831-L844)

### model_dump

```python
def model_dump(self) -> dict[str, Any]:
```

Return a new native wire-data dictionary without validating again.

[Source: python/yosoi/contracts.py:846](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L846-L848)

### model_dump_json

```python
def model_dump_json(self) -> str:
```

Return native wire JSON with evidence and terminal states preserved.

[Source: python/yosoi/contracts.py:850](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L850-L852)

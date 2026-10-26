---
title: "ContractRecordIssue"
description: "yosoi.contracts.ContractRecordIssue Python API reference."
order: 0
---

`yosoi.contracts.ContractRecordIssue`

```python
class ContractRecordIssue:
```

One rejected candidate with Pydantic details and source evidence.

Attributes:
    candidate: Original candidate with all field findings.
    field_ids: Authored field IDs responsible for rejection.
    kind: missing_required, excess_candidates, incomplete_evidence, or
        validation_error.
    observed: Finding count for excess_candidates when available.
    evidence: Findings for the affected field IDs, without copying source text.
    error: Original Pydantic ValidationError, when model validation ran.

[Source: python/yosoi/contracts.py:818](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L818-L876)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
candidate: Candidate = dataclass_field(repr=False)
field_ids: tuple[str, ...]
kind: str
evidence: tuple[Finding, ...] = dataclass_field(repr=False)
error: ValidationError | None = dataclass_field(default=None, repr=False)
observed: int | None = None
field_kinds: tuple[tuple[str, str], ...] = ()
```

## Methods

### errors

```python
@property
def errors(self) -> tuple[dict[str, Any], ...]:
```

Return Pydantic error details without input values or documentation URLs.

[Source: python/yosoi/contracts.py:840](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L840-L851)

### fields

```python
@property
def fields(self) -> tuple[FieldIssue, ...]:
```

Return Rust-compatible field summaries with exact source evidence.

[Source: python/yosoi/contracts.py:854](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L854-L876)

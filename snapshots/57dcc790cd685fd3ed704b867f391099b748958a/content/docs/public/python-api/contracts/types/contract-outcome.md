---
title: "ContractOutcome"
description: "yosoi.contracts.ContractOutcome Python API reference."
order: 0
---

`yosoi.contracts.ContractOutcome`

```python
class ContractOutcome[T: 'Contract'](_ReadOnlyView):
```

Read-only evaluation retaining accepted and rejected candidates.

Attributes:
    contract: Typed record definition used for validation.
    status: evaluated, no_match, indeterminate, locate_failed, extraction_rejected,
        or validation_rejected retains the phase distinction.
    document_id: Evidence document identity when available.
    failure: Typed phase or operation-budget rejection when present.
    completeness: Partial or unknown coverage for indeterminate outcomes.
    reason_code: Structural explanation of indeterminate coverage.
    records: Accepted typed values and original candidate evidence.
    issues: Rejected candidates with field-specific reasons and findings.
    extraction_diagnostics: Nonfatal grouping issues preventing an all-accepted
        claim.

[Source: python/yosoi/contracts.py:855](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L855-L975)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, contract: type[T], handle: _native.ContractOutcome) -> None:
```

Retain a native evaluation handle and read-only typed results.

Args:
    contract: Definition used to interpret converted values.
    handle: Native validation outcome from the Rust pipeline.

Rust results are reconstructed without Python validators or defaults changing
accepted records. Construction does not acquire documents.

[Source: python/yosoi/contracts.py:885](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L885-L945)

### require_all

```python
def require_all(self) -> list[T]:
```

Return values only when no record or extraction issue remains.

Returns:
    A new typed list, empty for complete no-match. The original outcome
    remains available for inspection of evidence and rejected records.

Raises:
    ContractIssues: Issues, indeterminate evidence, or failed phases prevent
        an all-accepted result.

[Source: python/yosoi/contracts.py:947](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L947-L961)

### to_archived

```python
def to_archived(self) -> ArchivedContractOutcome:
```

Return Rust's code-independent portable archive representation.

[Source: python/yosoi/contracts.py:963](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L963-L967)

### model_dump

```python
def model_dump(self) -> dict[str, Any]:
```

Return a new native wire-data dictionary without validating again.

[Source: python/yosoi/contracts.py:969](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L969-L971)

### model_dump_json

```python
def model_dump_json(self) -> str:
```

Return native wire JSON with evidence and terminal states preserved.

[Source: python/yosoi/contracts.py:973](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L973-L975)

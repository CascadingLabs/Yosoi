---
title: "ContractOutcome"
description: "yosoi.contracts.ContractOutcome Python API reference."
order: 0
---

`yosoi.contracts.ContractOutcome`

```python
class ContractOutcome[T: 'Contract'](_ReadOnlyView):
```

Pydantic validation report retaining accepted and rejected candidates.

Attributes:
    contract: Typed record definition used for validation.
    status: evaluated, no_match, indeterminate, locate_failed,
        extraction_rejected, or validation_rejected.
    document_id: Evidence document identity when available.
    failure: Typed phase or operation-budget rejection when present.
    completeness: Partial or unknown coverage for indeterminate outcomes.
    reason_code: Structural explanation of indeterminate coverage.
    candidates: All complete-candidate evidence retained by native extraction.
    records: Accepted Pydantic values paired with original candidates.
    issues: Rejected candidates with Pydantic error details and findings.
    extraction_diagnostics: Nonfatal grouping issues retained alongside accepted
        values; strict all-record access treats them as rejection facts.

[Source: python/yosoi/contracts.py:939](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L939-L1178)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, extracted: Extracted[T], policy: ExtractionPolicy) -> None:
```

Validate each complete candidate under the supplied resource limits.

Args:
    extracted: Raw candidates from Rust's bounded extraction stage.
    policy: Minimum acceptance and validation-work limits.

[Source: python/yosoi/contracts.py:972](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L972-L1088)

### accepted_records

```python
@property
def accepted_records(self) -> tuple[T, ...]:
```

Return the accepted model values without their evidence wrappers.

[Source: python/yosoi/contracts.py:1091](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L1091-L1093)

### meets_minimum_records

```python
@property
def meets_minimum_records(self) -> bool:
```

Return whether accepted values meet this report's requested minimum.

[Source: python/yosoi/contracts.py:1096](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L1096-L1098)

### require_all

```python
def require_all(self) -> list[T]:
```

Return bare values only when the report is fully acceptable.

Returns:
    A mutable list of accepted Pydantic models. The report keeps its evidence.

Raises:
    ContractIssues: Rejected candidates, terminal states, or an unmet minimum
        prevent an all-accepted result.

[Source: python/yosoi/contracts.py:1100](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L1100-L1124)

### to_archived

```python
def to_archived(self) -> ArchivedContractOutcome:
```

Reject Python-to-Rust archive conversion and name the portable API.

[Source: python/yosoi/contracts.py:1126](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L1126-L1131)

### model_dump

```python
def model_dump(self) -> dict[str, Any]:
```

Return report metadata and safe Pydantic validation details.

[Source: python/yosoi/contracts.py:1133](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L1133-L1174)

### model_dump_json

```python
def model_dump_json(self) -> str:
```

Return JSON report details without Pydantic error inputs.

[Source: python/yosoi/contracts.py:1176](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L1176-L1178)

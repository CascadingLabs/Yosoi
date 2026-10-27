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

[Source: python/yosoi/contracts.py:879](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L879-L1118)

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

[Source: python/yosoi/contracts.py:912](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L912-L1028)

### accepted_records

```python
@property
def accepted_records(self) -> tuple[T, ...]:
```

Return the accepted model values without their evidence wrappers.

[Source: python/yosoi/contracts.py:1031](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L1031-L1033)

### meets_minimum_records

```python
@property
def meets_minimum_records(self) -> bool:
```

Return whether accepted values meet this report's requested minimum.

[Source: python/yosoi/contracts.py:1036](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L1036-L1038)

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

[Source: python/yosoi/contracts.py:1040](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L1040-L1064)

### to_archived

```python
def to_archived(self) -> ArchivedContractOutcome:
```

Reject Python-to-Rust archive conversion and name the portable API.

[Source: python/yosoi/contracts.py:1066](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L1066-L1071)

### model_dump

```python
def model_dump(self) -> dict[str, Any]:
```

Return report metadata and safe Pydantic validation details.

[Source: python/yosoi/contracts.py:1073](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L1073-L1114)

### model_dump_json

```python
def model_dump_json(self) -> str:
```

Return JSON report details without Pydantic error inputs.

[Source: python/yosoi/contracts.py:1116](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L1116-L1118)

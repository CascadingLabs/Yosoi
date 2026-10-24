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

[Source: python/yosoi/contracts.py:770](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/contracts.py#L770-L874)

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

[Source: python/yosoi/contracts.py:797](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/contracts.py#L797-L843)

### validate

```python
def validate(self, *, limits: ValidationLimits | None=None, policy: ExtractionPolicy | None=None) -> ContractOutcome[T]:
```

Run Pydantic validation after checking bounded native-work limits.

Args:
    limits: Validation-work budgets, or None for Rust defaults.
    policy: Acceptance policy. An explicit ``limits`` value overrides its
        ``validation_limits`` member.

Returns:
    Pydantic-accepted records, candidate issues, or terminal states. User
    validators are skipped when extraction evidence is incomplete or the
    validation-work budget is exceeded.

[Source: python/yosoi/contracts.py:845](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/contracts.py#L845-L866)

### model_dump

```python
def model_dump(self) -> dict[str, Any]:
```

Return a new native wire-data dictionary without validating again.

[Source: python/yosoi/contracts.py:868](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/contracts.py#L868-L870)

### model_dump_json

```python
def model_dump_json(self) -> str:
```

Return native wire JSON with evidence and terminal states preserved.

[Source: python/yosoi/contracts.py:872](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/contracts.py#L872-L874)

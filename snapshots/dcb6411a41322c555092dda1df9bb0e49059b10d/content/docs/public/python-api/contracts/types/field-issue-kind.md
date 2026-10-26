---
title: "FieldIssueKind"
description: "yosoi.contracts.FieldIssueKind Python API reference."
order: 0
---

`yosoi.contracts.FieldIssueKind`

```python
class FieldIssueKind(ImmutableModel):
```

Cardinality, completeness, or projection conversion rejection.

Attributes:
    kind: Selects missing_required, excess_candidates, incomplete_evidence,
        unsupported_projected_value, or conversion_failed.
    observed: Finding count for excess_candidates, when applicable.

[Source: python/yosoi/contracts.py:360](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L360-L376)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['missing_required', 'excess_candidates', 'incomplete_evidence', 'unsupported_projected_value', 'conversion_failed']
observed: int | None = None
```

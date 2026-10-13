---
title: "FieldIssueKind"
description: "yosoi.contracts.FieldIssueKind Python API reference."
order: 0
---

`yosoi.contracts.FieldIssueKind`

```python
class FieldIssueKind(ImmutableModel):
```

Cardinality, completeness, conversion, or semantic field rejection.

Attributes:
    kind: Selects missing_required, excess_candidates, incomplete_evidence,
        unsupported_projected_value, conversion_failed, or
        semantic_validation_failed.
    observed: Finding count for excess_candidates, when applicable.
    code: negative_money when converted money violates supported nonnegative
        semantics.

[Source: python/yosoi/contracts.py:339](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L339-L360)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['missing_required', 'excess_candidates', 'incomplete_evidence', 'unsupported_projected_value', 'conversion_failed', 'semantic_validation_failed']
observed: int | None = None
code: Literal['negative_money'] | None = None
```

---
title: "FieldIssue"
description: "yosoi.contracts.FieldIssue Python API reference."
order: 0
---

`yosoi.contracts.FieldIssue`

```python
class FieldIssue(ImmutableModel):
```

Rejected Contract field with supporting source-derived evidence.

Attributes:
    field: Authored identifier of the rejected field.
    kind: Typed field rejection explanation, separate from operation budgets.
    evidence: Findings supporting the issue; they can contain user or source
        content.

[Source: python/yosoi/contracts.py:429](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/contracts.py#L429-L441)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
field: FieldId
kind: FieldIssueKind
evidence: tuple[Finding, ...] = PydanticField(repr=False)
```

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

[Source: python/yosoi/contracts.py:379](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L379-L391)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
field: FieldId
kind: FieldIssueKind
evidence: tuple[Finding, ...] = PydanticField(repr=False)
```

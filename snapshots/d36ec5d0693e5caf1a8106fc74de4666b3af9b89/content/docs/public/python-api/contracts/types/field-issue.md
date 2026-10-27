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

[Source: python/yosoi/contracts.py:379](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/contracts.py#L379-L391)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
field: FieldId
kind: FieldIssueKind
evidence: tuple[Finding, ...] = PydanticField(repr=False)
```

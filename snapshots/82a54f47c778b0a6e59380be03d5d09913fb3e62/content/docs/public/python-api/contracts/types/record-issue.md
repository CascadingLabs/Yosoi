---
title: "RecordIssue"
description: "yosoi.contracts.RecordIssue Python API reference."
order: 0
---

`yosoi.contracts.RecordIssue`

```python
class RecordIssue(ImmutableModel):
```

Rejected candidate record with retained field issues.

Attributes:
    candidate: Original grouped evidence for the rejected record.
    fields: Field rejection reasons and supporting findings.

[Source: python/yosoi/contracts.py:402](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/contracts.py#L402-L411)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
candidate: SerializeAsAny[Candidate]
fields: tuple[FieldIssue, ...]
```

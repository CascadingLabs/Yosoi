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

[Source: python/yosoi/contracts.py:468](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L468-L477)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
candidate: SerializeAsAny[Candidate]
fields: tuple[FieldIssue, ...]
```

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

[Source: python/yosoi/contracts.py:418](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/contracts.py#L418-L427)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
candidate: SerializeAsAny[Candidate]
fields: tuple[FieldIssue, ...]
```

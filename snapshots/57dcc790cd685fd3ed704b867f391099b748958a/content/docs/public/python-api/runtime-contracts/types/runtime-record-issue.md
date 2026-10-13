---
title: "RuntimeRecordIssue"
description: "yosoi.runtime_contracts.RuntimeRecordIssue Python API reference."
order: 0
---

`yosoi.runtime_contracts.RuntimeRecordIssue`

```python
class RuntimeRecordIssue(ImmutableModel):
```

Retain a rejected candidate and its field validation issues.

Attributes:
    candidate: Raw findings for the candidate that failed validation.
    fields: Field-specific cardinality, conversion, or provenance issues.

[Source: python/yosoi/runtime_contracts.py:187](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L187-L196)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
candidate: RuntimeCandidate
fields: tuple[FieldIssue, ...]
```

---
title: "ValidatedRecord"
description: "yosoi.contracts.ValidatedRecord Python API reference."
order: 0
---

`yosoi.contracts.ValidatedRecord`

```python
class ValidatedRecord[T: 'Contract'](ImmutableModel):
```

Pydantic-accepted typed value with original candidate evidence retained.

Attributes:
    value: Record accepted by the Contract's Pydantic model validators.
    candidate: Original grouped findings and provenance.

[Source: python/yosoi/contracts.py:456](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L456-L465)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
value: SerializeAsAny[T] = PydanticField(repr=False)
candidate: SerializeAsAny[Candidate] = PydanticField(repr=False)
```

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

[Source: python/yosoi/contracts.py:406](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L406-L415)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
value: SerializeAsAny[T] = PydanticField(repr=False)
candidate: SerializeAsAny[Candidate] = PydanticField(repr=False)
```

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

[Source: python/yosoi/contracts.py:406](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L406-L415)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
value: SerializeAsAny[T] = PydanticField(repr=False)
candidate: SerializeAsAny[Candidate] = PydanticField(repr=False)
```

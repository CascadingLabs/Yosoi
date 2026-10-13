---
title: "ValidatedRecord"
description: "yosoi.contracts.ValidatedRecord Python API reference."
order: 0
---

`yosoi.contracts.ValidatedRecord`

```python
class ValidatedRecord[T: 'Contract'](ImmutableModel):
```

Accepted typed value with original candidate evidence retained.

Attributes:
    value: Record accepted by Rust cardinality, conversion, and semantics.
    candidate: Original grouped findings and provenance.

[Source: python/yosoi/contracts.py:390](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L390-L399)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
value: SerializeAsAny[T] = PydanticField(repr=False)
candidate: SerializeAsAny[Candidate] = PydanticField(repr=False)
```

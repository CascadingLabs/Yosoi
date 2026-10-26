---
title: "Unprojectable"
description: "yosoi.request.Unprojectable Python API reference."
order: 0
---

`yosoi.request.Unprojectable`

```python
class Unprojectable(ImmutableModel):
```

Available acquisition evidence cannot produce the requested representation.

Attributes:
    status: Discriminator fixed to unprojectable for tagged decoding.
    reason: Typed projection incompatibility or unsupported representation
        explanation.

[Source: python/yosoi/request.py:141](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/request.py#L141-L156)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
status: Literal['unprojectable']
reason: ProjectionReason
```

## Methods

### document

```python
@property
def document(self) -> None:
```

Return None because the requested representation cannot be projected.

[Source: python/yosoi/request.py:154](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/request.py#L154-L156)

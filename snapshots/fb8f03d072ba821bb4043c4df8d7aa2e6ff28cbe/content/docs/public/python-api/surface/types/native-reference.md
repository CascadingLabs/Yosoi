---
title: "NativeReference"
description: "yosoi.surface.NativeReference Python API reference."
order: 0
---

`yosoi.surface.NativeReference`

```python
class NativeReference(ImmutableModel):
```

Exact document-index address; it does not grant action permission.

[Source: python/yosoi/surface.py:128](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L128-L134)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
capture: StrictStr = Field(description='Immutable document interpretation identity.')
node: int = Field(strict=True, ge=0, description='Producer-issued node ordinal.')
```

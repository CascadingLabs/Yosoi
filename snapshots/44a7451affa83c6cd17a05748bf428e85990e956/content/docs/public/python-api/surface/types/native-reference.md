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

[Source: python/yosoi/surface.py:128](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L128-L134)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
capture: StrictStr = Field(description='Immutable document interpretation identity.')
node: int = Field(strict=True, ge=0, description='Producer-issued node ordinal.')
```

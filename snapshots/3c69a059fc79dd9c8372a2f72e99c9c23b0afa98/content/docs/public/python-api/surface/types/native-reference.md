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

[Source: python/yosoi/surface.py:121](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L121-L127)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
capture: StrictStr = Field(description='Immutable document interpretation identity.')
node: int = Field(strict=True, ge=0, description='Producer-issued node ordinal.')
```

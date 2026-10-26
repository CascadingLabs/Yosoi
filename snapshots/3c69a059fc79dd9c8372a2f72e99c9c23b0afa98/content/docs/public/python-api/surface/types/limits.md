---
title: "Limits"
description: "yosoi.surface.Limits Python API reference."
order: 0
---

`yosoi.surface.Limits`

```python
class Limits(ImmutableModel):
```

Task-independent document preparation bounds, enforced by Rust.

[Source: python/yosoi/surface.py:93](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L93-L107)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
input_bytes: int = Field(default=8388608, strict=True, ge=0, description='Input byte cap.')
nodes: int = Field(default=200000, strict=True, ge=0, description='Indexed node cap.')
depth: int = Field(default=96, strict=True, ge=0, description='Source tree depth cap.')
overview_depth: int = Field(default=6, strict=True, ge=0, description='Automatic zoom depth.')
```

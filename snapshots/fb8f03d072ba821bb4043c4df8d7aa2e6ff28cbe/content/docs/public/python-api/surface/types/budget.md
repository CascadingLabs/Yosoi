---
title: "Budget"
description: "yosoi.surface.Budget Python API reference."
order: 0
---

`yosoi.surface.Budget`

```python
class Budget(ImmutableModel):
```

Bounds on the complete Rust JSON result, before a transport envelope.

[Source: python/yosoi/surface.py:89](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L89-L97)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
bytes: int = Field(default=4096, strict=True, ge=0, description='UTF-8 JSON byte limit.')
items: int = Field(default=20, strict=True, ge=0, description='Maximum routing entries.')
```

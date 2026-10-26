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

[Source: python/yosoi/surface.py:89](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L89-L97)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
bytes: int = Field(default=4096, strict=True, ge=0, description='UTF-8 JSON byte limit.')
items: int = Field(default=20, strict=True, ge=0, description='Maximum routing entries.')
```

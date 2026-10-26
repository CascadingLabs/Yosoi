---
title: "Coordinate"
description: "yosoi.surface.Coordinate Python API reference."
order: 0
---

`yosoi.surface.Coordinate`

```python
class Coordinate(ImmutableModel):
```

Representation-specific locator coordinates retained by the index.

[Source: python/yosoi/surface.py:202](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L202-L206)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: StrictStr = Field(description='Coordinate interpretation.')
value: StrictStr = Field(description='Producer-derived coordinate value.')
```

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

[Source: python/yosoi/surface.py:202](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L202-L206)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: StrictStr = Field(description='Coordinate interpretation.')
value: StrictStr = Field(description='Producer-derived coordinate value.')
```

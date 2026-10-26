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

[Source: python/yosoi/surface.py:195](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L195-L199)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: StrictStr = Field(description='Coordinate interpretation.')
value: StrictStr = Field(description='Producer-derived coordinate value.')
```

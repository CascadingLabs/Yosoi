---
title: "Observation"
description: "yosoi.surface.Observation Python API reference."
order: 0
---

`yosoi.surface.Observation`

```python
class Observation(ImmutableModel):
```

One immutable interpretation of a continuing surface.

[Source: python/yosoi/surface.py:245](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L245-L250)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: ObservationId = Field(description='Exact observation identity.')
surface: SurfaceId = Field(description='Surface represented by this observation.')
coverage: Coverage = Field(description='Evidence completeness.')
```

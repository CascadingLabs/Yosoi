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

[Source: python/yosoi/surface.py:252](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L252-L257)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: ObservationId = Field(description='Exact observation identity.')
surface: SurfaceId = Field(description='Surface represented by this observation.')
coverage: Coverage = Field(description='Evidence completeness.')
```

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

[Source: python/yosoi/surface.py:252](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L252-L257)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: ObservationId = Field(description='Exact observation identity.')
surface: SurfaceId = Field(description='Surface represented by this observation.')
coverage: Coverage = Field(description='Evidence completeness.')
```

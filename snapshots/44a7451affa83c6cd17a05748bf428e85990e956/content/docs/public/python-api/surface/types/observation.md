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

[Source: python/yosoi/surface.py:252](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L252-L257)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: ObservationId = Field(description='Exact observation identity.')
surface: SurfaceId = Field(description='Surface represented by this observation.')
coverage: Coverage = Field(description='Evidence completeness.')
```

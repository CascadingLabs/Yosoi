---
title: "Expand"
description: "yosoi.surface.Expand Python API reference."
order: 0
---

`yosoi.surface.Expand`

```python
class Expand(ImmutableModel):
```

Request direct structural or temporal children of exact evidence.

[Source: python/yosoi/surface.py:266](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L266-L270)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['expand'] = Field(default='expand', description='Operation tag.')
reference: Reference = Field(description='Exact region to explore.')
```

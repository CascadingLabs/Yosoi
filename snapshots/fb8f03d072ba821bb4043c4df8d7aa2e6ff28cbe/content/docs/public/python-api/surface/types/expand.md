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

[Source: python/yosoi/surface.py:266](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L266-L270)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['expand'] = Field(default='expand', description='Operation tag.')
reference: Reference = Field(description='Exact region to explore.')
```

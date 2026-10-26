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

[Source: python/yosoi/surface.py:259](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L259-L263)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['expand'] = Field(default='expand', description='Operation tag.')
reference: Reference = Field(description='Exact region to explore.')
```

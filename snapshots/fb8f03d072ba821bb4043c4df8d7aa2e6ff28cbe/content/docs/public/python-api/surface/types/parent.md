---
title: "Parent"
description: "yosoi.surface.Parent Python API reference."
order: 0
---

`yosoi.surface.Parent`

```python
class Parent(ImmutableModel):
```

Request a structural parent where that relation is supported.

[Source: python/yosoi/surface.py:287](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L287-L291)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['parent'] = Field(default='parent', description='Operation tag.')
reference: Reference = Field(description='Evidence whose parent is requested.')
```

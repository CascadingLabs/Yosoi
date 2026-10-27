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

[Source: python/yosoi/surface.py:287](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L287-L291)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['parent'] = Field(default='parent', description='Operation tag.')
reference: Reference = Field(description='Evidence whose parent is requested.')
```

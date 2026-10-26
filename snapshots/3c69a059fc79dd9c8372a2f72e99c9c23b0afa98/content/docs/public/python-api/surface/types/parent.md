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

[Source: python/yosoi/surface.py:280](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L280-L284)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['parent'] = Field(default='parent', description='Operation tag.')
reference: Reference = Field(description='Evidence whose parent is requested.')
```

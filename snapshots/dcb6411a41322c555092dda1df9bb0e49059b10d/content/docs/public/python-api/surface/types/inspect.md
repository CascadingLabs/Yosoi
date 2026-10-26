---
title: "Inspect"
description: "yosoi.surface.Inspect Python API reference."
order: 0
---

`yosoi.surface.Inspect`

```python
class Inspect(ImmutableModel):
```

Request source-backed text detail, possibly split across chunks.

[Source: python/yosoi/surface.py:273](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L273-L277)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['inspect'] = Field(default='inspect', description='Operation tag.')
reference: Reference = Field(description='Exact selected evidence.')
```

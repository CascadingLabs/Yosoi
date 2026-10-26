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

[Source: python/yosoi/surface.py:266](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L266-L270)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['inspect'] = Field(default='inspect', description='Operation tag.')
reference: Reference = Field(description='Exact selected evidence.')
```

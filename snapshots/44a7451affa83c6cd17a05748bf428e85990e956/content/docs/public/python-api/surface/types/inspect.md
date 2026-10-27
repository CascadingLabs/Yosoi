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

[Source: python/yosoi/surface.py:273](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L273-L277)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['inspect'] = Field(default='inspect', description='Operation tag.')
reference: Reference = Field(description='Exact selected evidence.')
```

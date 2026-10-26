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

[Source: python/yosoi/surface.py:273](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L273-L277)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['inspect'] = Field(default='inspect', description='Operation tag.')
reference: Reference = Field(description='Exact selected evidence.')
```

---
title: "ParentResult"
description: "yosoi.surface.ParentResult Python API reference."
order: 0
---

`yosoi.surface.ParentResult`

```python
class ParentResult(ImmutableModel):
```

Tagged parent result; a root has no parent.

[Source: python/yosoi/surface.py:363](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L363-L367)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['parent'] = Field(default='parent', description='Result tag.')
data: Reference | None = Field(description='Parent reference, absent at root.')
```

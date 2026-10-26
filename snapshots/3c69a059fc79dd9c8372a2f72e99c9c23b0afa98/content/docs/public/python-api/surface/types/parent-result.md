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

[Source: python/yosoi/surface.py:356](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L356-L360)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['parent'] = Field(default='parent', description='Result tag.')
data: Reference | None = Field(description='Parent reference, absent at root.')
```

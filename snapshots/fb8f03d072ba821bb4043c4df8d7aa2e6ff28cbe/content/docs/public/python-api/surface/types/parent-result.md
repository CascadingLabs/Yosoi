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

[Source: python/yosoi/surface.py:363](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L363-L367)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['parent'] = Field(default='parent', description='Result tag.')
data: Reference | None = Field(description='Parent reference, absent at root.')
```

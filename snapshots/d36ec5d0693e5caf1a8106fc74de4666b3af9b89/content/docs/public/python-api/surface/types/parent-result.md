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

[Source: python/yosoi/surface.py:363](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L363-L367)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['parent'] = Field(default='parent', description='Result tag.')
data: Reference | None = Field(description='Parent reference, absent at root.')
```

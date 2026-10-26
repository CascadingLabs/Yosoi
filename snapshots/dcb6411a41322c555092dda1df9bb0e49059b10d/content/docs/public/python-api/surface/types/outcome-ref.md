---
title: "OutcomeRef"
description: "yosoi.surface.OutcomeRef Python API reference."
order: 0
---

`yosoi.surface.OutcomeRef`

```python
class OutcomeRef(ImmutableModel):
```

Typed immutable reference selecting an outcome through Archive.read.

[Source: python/yosoi/surface.py:976](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L976-L991)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document: StrictStr = Field(description='Existing Archive Document reference.')
version: int = Field(default=1, strict=True, ge=0, le=2 ** 32 - 1, description='Logical version, checked for support during Archive.read.')
```

---
title: "Continuation"
description: "yosoi.surface.Continuation Python API reference."
order: 0
---

`yosoi.surface.Continuation`

```python
class Continuation(ImmutableModel):
```

Opaque native-index continuation. Copy it unchanged into the same read.

[Source: python/yosoi/surface.py:146](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L146-L155)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
capture: StrictStr = Field(description='Original immutable capture.')
operation: StrictStr = Field(description='Original operation binding.')
scope: int = Field(strict=True, ge=0, description='Original producer scope.')
query: StrictStr = Field(description='Original literal-search binding.')
offset: int = Field(strict=True, ge=0, description='Next entry or UTF-8 byte offset.')
```

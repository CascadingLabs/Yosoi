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

[Source: python/yosoi/surface.py:139](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L139-L148)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
capture: StrictStr = Field(description='Original immutable capture.')
operation: StrictStr = Field(description='Original operation binding.')
scope: int = Field(strict=True, ge=0, description='Original producer scope.')
query: StrictStr = Field(description='Original literal-search binding.')
offset: int = Field(strict=True, ge=0, description='Next entry or UTF-8 byte offset.')
```

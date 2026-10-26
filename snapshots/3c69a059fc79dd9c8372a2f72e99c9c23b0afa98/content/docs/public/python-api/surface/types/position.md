---
title: "Position"
description: "yosoi.surface.Position Python API reference."
order: 0
---

`yosoi.surface.Position`

```python
class Position(ImmutableModel):
```

Saved navigation state without granting live access or control.

[Source: python/yosoi/surface.py:894](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L894-L903)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
scope: NativeReference | None = Field(default=None, description='Expanded region.')
focus: NativeReference | None = Field(default=None, description='Selected evidence.')
continuation: Continuation | None = Field(default=None, description='Saved read position.')
```

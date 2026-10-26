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

[Source: python/yosoi/surface.py:1277](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1277-L1286)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
scope: NativeReference | None = Field(default=None, description='Expanded region.')
focus: NativeReference | None = Field(default=None, description='Selected evidence.')
continuation: Continuation | None = Field(default=None, description='Saved read position.')
```

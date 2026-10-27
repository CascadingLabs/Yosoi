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

[Source: python/yosoi/surface.py:1277](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L1277-L1286)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
scope: NativeReference | None = Field(default=None, description='Expanded region.')
focus: NativeReference | None = Field(default=None, description='Selected evidence.')
continuation: Continuation | None = Field(default=None, description='Saved read position.')
```

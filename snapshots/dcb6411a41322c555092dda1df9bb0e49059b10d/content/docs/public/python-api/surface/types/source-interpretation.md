---
title: "SourceInterpretation"
description: "yosoi.surface.SourceInterpretation Python API reference."
order: 0
---

`yosoi.surface.SourceInterpretation`

```python
class SourceInterpretation(ImmutableModel):
```

Interpreter for an exact document, image or named observation bundle.

[Source: python/yosoi/surface.py:898](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L898-L923)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['document', 'image', 'bundle'] = Field(default='document', description='Interpreter category.')
tile_side: int | None = Field(default=None, strict=True, ge=0, le=2 ** 32 - 1, description='Original image tile size, used only for images.')
```

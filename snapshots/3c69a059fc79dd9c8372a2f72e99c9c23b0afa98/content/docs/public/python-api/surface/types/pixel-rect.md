---
title: "PixelRect"
description: "yosoi.surface.PixelRect Python API reference."
order: 0
---

`yosoi.surface.PixelRect`

```python
class PixelRect(ImmutableModel):
```

Crop in full decoded-frame pixels; source-video dimensions may differ.

[Source: python/yosoi/surface.py:622](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L622-L632)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
x: int = Field(strict=True, ge=0, le=2 ** 32 - 1, description='Left pixel coordinate.')
y: int = Field(strict=True, ge=0, le=2 ** 32 - 1, description='Top pixel coordinate.')
width: int = Field(strict=True, ge=0, le=2 ** 32 - 1, description='Crop pixel width.')
height: int = Field(strict=True, ge=0, le=2 ** 32 - 1, description='Crop pixel height.')
```

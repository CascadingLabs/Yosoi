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

[Source: python/yosoi/surface.py:629](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L629-L639)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
x: int = Field(strict=True, ge=0, le=2 ** 32 - 1, description='Left pixel coordinate.')
y: int = Field(strict=True, ge=0, le=2 ** 32 - 1, description='Top pixel coordinate.')
width: int = Field(strict=True, ge=0, le=2 ** 32 - 1, description='Crop pixel width.')
height: int = Field(strict=True, ge=0, le=2 ** 32 - 1, description='Crop pixel height.')
```

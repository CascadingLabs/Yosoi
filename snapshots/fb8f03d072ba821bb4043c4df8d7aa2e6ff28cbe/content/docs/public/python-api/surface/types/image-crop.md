---
title: "ImageCrop"
description: "yosoi.surface.ImageCrop Python API reference."
order: 0
---

`yosoi.surface.ImageCrop`

```python
class ImageCrop(ImmutableModel):
```

Actual PNG evidence cropped from an indexed immutable image region.

[Source: python/yosoi/surface.py:642](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L642-L647)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
reference: NativeReference = Field(description='Exact selected image evidence.')
rect: PixelRect = Field(description='Bounds in original decoded image pixels.')
png: bytes = Field(description='Encoded PNG bytes, independent of text budgets.')
```

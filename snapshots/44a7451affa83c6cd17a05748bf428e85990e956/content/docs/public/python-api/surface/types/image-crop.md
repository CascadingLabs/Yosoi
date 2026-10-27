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

[Source: python/yosoi/surface.py:642](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L642-L647)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
reference: NativeReference = Field(description='Exact selected image evidence.')
rect: PixelRect = Field(description='Bounds in original decoded image pixels.')
png: bytes = Field(description='Encoded PNG bytes, independent of text budgets.')
```

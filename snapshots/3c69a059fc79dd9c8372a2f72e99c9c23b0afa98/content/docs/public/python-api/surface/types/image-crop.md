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

[Source: python/yosoi/surface.py:635](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L635-L640)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
reference: NativeReference = Field(description='Exact selected image evidence.')
rect: PixelRect = Field(description='Bounds in original decoded image pixels.')
png: bytes = Field(description='Encoded PNG bytes, independent of text budgets.')
```

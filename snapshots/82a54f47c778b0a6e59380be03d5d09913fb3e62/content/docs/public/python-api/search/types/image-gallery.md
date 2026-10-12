---
title: "ImageGallery"
description: "yosoi.search.ImageGallery Python API reference."
order: 0
---

`yosoi.search.ImageGallery`

```python
class ImageGallery(ImmutableModel):
```

A provider-displayed collection of image results, without an organic rank.

Attributes:
    kind: Discriminator fixed to image_gallery for tagged decoding.
    placement_index: One-based position of the gallery among provider-page
        placements.
    images: Image and source-page destinations extracted from the gallery.

[Source: python/yosoi/search.py:275](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/search.py#L275-L296)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['image_gallery']
placement_index: Rank
images: tuple[ImageResult, ...] = Field(repr=False)
```

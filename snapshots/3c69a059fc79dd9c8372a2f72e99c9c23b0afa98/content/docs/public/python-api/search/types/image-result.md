---
title: "ImageResult"
description: "yosoi.search.ImageResult Python API reference."
order: 0
---

`yosoi.search.ImageResult`

```python
class ImageResult(ImmutableModel):
```

An image destination paired with its reported hosting page.

Attributes:
    image_url: Validated image destination; no bytes are downloaded by this model.
    source_page_url: Validated source-page destination reported by the provider.

[Source: python/yosoi/search.py:191](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/search.py#L191-L206)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
image_url: SearchResultUrl = Field(repr=False)
source_page_url: SearchResultUrl = Field(repr=False)
```

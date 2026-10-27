---
title: "SearchFeature"
description: "yosoi.search.SearchFeature Python API reference."
order: 0
---

`yosoi.search.SearchFeature`

```python
SearchFeature = Annotated[Sponsored | Answer | ImageGallery | LocalPack, Field(discriminator='kind')]
```

Tagged rich placements separate from organic rank: sponsored content, answers, image
galleries, and local packs. Reported destinations are not fetched by these values.

[Source: python/yosoi/search.py:324](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/search.py#L324-L326)

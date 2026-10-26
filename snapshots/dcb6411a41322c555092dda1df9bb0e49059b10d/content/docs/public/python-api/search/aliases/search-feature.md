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

[Source: python/yosoi/search.py:324](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/search.py#L324-L326)

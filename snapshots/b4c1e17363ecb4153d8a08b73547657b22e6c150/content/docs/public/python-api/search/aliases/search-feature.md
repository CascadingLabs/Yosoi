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

[Source: python/yosoi/search.py:324](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/search.py#L324-L326)

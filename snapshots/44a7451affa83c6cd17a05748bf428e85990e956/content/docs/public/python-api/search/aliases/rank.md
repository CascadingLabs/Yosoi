---
title: "Rank"
description: "yosoi.search.Rank Python API reference."
order: 0
---

`yosoi.search.Rank`

```python
Rank = Annotated[int, Field(ge=1, le=65535, strict=True)]
```

Strict one-based u16 position. Organic rank and provider placement are different
coordinates and can contain gaps.

[Source: python/yosoi/search.py:77](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/search.py#L77-L77)

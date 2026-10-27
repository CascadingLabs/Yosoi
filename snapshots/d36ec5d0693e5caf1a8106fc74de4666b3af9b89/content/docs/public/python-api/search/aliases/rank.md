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

[Source: python/yosoi/search.py:77](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/search.py#L77-L77)

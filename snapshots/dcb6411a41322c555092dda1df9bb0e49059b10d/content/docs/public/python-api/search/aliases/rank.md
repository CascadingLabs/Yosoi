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

[Source: python/yosoi/search.py:77](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/search.py#L77-L77)

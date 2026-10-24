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

[Source: python/yosoi/search.py:77](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/search.py#L77-L77)

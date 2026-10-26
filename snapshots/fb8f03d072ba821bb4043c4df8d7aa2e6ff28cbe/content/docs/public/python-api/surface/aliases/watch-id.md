---
title: "WatchId"
description: "yosoi.surface.WatchId Python API reference."
order: 0
---

`yosoi.surface.WatchId`

```python
WatchId = Annotated[int, Field(strict=True, ge=0, le=2 ** 64 - 1)]
```

Session-local subscription integer, checked against the owning Rust cursor.

[Source: python/yosoi/surface.py:85](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L85-L85)

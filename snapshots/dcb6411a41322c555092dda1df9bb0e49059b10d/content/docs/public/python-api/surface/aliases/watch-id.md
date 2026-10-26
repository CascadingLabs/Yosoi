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

[Source: python/yosoi/surface.py:85](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L85-L85)

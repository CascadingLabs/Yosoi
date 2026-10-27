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

[Source: python/yosoi/surface.py:85](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L85-L85)

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

[Source: python/yosoi/surface.py:78](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L78-L78)

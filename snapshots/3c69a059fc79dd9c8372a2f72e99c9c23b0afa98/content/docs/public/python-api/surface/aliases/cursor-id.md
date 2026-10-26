---
title: "CursorId"
description: "yosoi.surface.CursorId Python API reference."
order: 0
---

`yosoi.surface.CursorId`

```python
CursorId = Annotated[int, Field(strict=True, ge=0, le=2 ** 64 - 1)]
```

Session-local diagnostic integer. A copied ID never grants cursor authority.

[Source: python/yosoi/surface.py:76](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L76-L76)

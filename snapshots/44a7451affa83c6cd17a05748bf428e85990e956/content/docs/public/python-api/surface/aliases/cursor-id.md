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

[Source: python/yosoi/surface.py:83](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L83-L83)

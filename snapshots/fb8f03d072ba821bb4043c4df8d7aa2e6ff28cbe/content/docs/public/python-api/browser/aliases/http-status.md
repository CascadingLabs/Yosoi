---
title: "HttpStatus"
description: "yosoi.browser.HttpStatus Python API reference."
order: 0
---

`yosoi.browser.HttpStatus`

```python
HttpStatus = Annotated[int, Field(strict=True, ge=100, le=599)]
```

Strict integer HTTP status from 100 through 599; booleans are rejected.

[Source: python/yosoi/browser.py:72](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L72-L72)

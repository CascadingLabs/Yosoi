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

[Source: python/yosoi/browser.py:72](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L72-L72)

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

[Source: python/yosoi/browser.py:69](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/browser.py#L69-L69)

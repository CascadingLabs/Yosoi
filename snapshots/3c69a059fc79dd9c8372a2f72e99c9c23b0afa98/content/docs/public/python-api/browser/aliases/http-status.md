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

[Source: python/yosoi/browser.py:69](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L69-L69)

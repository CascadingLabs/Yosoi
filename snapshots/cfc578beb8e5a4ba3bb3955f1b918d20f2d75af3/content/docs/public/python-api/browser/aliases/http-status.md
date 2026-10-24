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

[Source: python/yosoi/browser.py:69](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L69-L69)

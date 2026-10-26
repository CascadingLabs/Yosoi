---
title: "ExecutionConcurrency"
description: "yosoi.browser.ExecutionConcurrency Python API reference."
order: 0
---

`yosoi.browser.ExecutionConcurrency`

```python
ExecutionConcurrency = Annotated[int, Field(strict=True, ge=1, le=32)]
```

Strict admitted execution capacity from one through 32 permits.

[Source: python/yosoi/browser.py:74](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L74-L74)

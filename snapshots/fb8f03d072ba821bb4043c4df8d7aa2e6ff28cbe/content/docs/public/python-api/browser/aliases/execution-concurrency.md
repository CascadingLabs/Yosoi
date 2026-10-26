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

[Source: python/yosoi/browser.py:74](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L74-L74)

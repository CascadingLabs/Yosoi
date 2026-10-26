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

[Source: python/yosoi/browser.py:71](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L71-L71)

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

[Source: python/yosoi/browser.py:71](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L71-L71)

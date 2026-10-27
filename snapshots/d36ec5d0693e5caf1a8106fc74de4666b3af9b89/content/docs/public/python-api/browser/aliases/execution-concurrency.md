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

[Source: python/yosoi/browser.py:74](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L74-L74)

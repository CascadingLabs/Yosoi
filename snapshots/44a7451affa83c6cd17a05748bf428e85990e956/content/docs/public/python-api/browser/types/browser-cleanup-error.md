---
title: "BrowserCleanupError"
description: "yosoi.browser.BrowserCleanupError Python API reference."
order: 0
---

`yosoi.browser.BrowserCleanupError`

```python
class BrowserCleanupError(RuntimeError):
```

Retain cleanup failures alongside the original operation exception.

Attributes:
    original_error: Exception raised before context cleanup failed.
    cleanup_errors: Cleanup exceptions retained in order.

[Source: python/yosoi/browser.py:1324](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L1324-L1346)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, original_error: BaseException, cleanup_errors: tuple[BaseException, ...]) -> None:
```

Preserve the operation exception alongside subsequent cleanup failures.

Args:
    original_error: Exception raised by the operation or caller cancellation.
    cleanup_errors: Exceptions raised while settling cleanup.

[Source: python/yosoi/browser.py:1332](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L1332-L1346)

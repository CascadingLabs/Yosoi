---
title: "navigate"
description: "yosoi.browser.navigate Python API reference."
order: 0
---

`yosoi.browser.navigate`

```python
def navigate(url: str) -> Navigate:
```

Declare navigation without acquiring or changing a browser.

Args:
    url: Nonempty destination URL.

Returns:
    Immutable Navigate step.

[Source: python/yosoi/browser.py:1496](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/browser.py#L1496-L1505)

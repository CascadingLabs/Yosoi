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

[Source: python/yosoi/browser.py:1595](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L1595-L1604)

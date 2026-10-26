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

[Source: python/yosoi/browser.py:1595](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L1595-L1604)

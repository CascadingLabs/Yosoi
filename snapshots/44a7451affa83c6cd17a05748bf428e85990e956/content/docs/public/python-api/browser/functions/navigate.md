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

[Source: python/yosoi/browser.py:1595](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L1595-L1604)

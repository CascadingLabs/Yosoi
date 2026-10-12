---
title: "evaluate"
description: "yosoi.browser.evaluate Python API reference."
order: 0
---

`yosoi.browser.evaluate`

```python
def evaluate(source: str) -> Evaluate:
```

Declare JavaScript evaluation without executing the source.

Args:
    source: Nonempty JavaScript source bounded to 65,536 characters.

Returns:
    Evaluate trigger requiring explicit JavaScript execution permission.

[Source: python/yosoi/browser.py:1624](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L1624-L1633)

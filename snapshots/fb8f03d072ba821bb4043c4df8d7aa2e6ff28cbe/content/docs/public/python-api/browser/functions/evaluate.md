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

[Source: python/yosoi/browser.py:1723](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L1723-L1732)

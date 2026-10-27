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

[Source: python/yosoi/browser.py:1723](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L1723-L1732)

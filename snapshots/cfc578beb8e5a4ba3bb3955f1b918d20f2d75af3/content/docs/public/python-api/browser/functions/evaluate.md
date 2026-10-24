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

[Source: python/yosoi/browser.py:1624](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L1624-L1633)

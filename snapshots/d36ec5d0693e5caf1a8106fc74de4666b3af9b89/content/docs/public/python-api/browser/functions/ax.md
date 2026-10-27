---
title: "ax"
description: "yosoi.browser.ax Python API reference."
order: 0
---

`yosoi.browser.ax`

```python
def ax(name: str, *, role: str | None=None) -> AccessibilityExpectation:
```

Declare an accessibility expectation for Until.

Args:
    name: Nonblank accessible name bounded to 4,096 UTF-8 bytes.
    role: Optional nonblank role bounded to 128 UTF-8 bytes.

Returns:
    AccessibilityExpectation based on browser accessibility evidence.

[Source: python/yosoi/browser.py:1799](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L1799-L1809)

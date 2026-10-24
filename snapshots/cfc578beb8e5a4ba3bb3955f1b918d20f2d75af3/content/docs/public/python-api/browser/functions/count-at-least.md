---
title: "count_at_least"
description: "yosoi.browser.count_at_least Python API reference."
order: 0
---

`yosoi.browser.count_at_least`

```python
def count_at_least(selector: str, count: int) -> ConditionExpectation:
```

Declare a minimum DOM match count for Until.

Args:
    selector: CSS selector for the current browser page.
    count: Unsigned minimum; zero is permitted.

Returns:
    ConditionExpectation requiring at least the declared match count.

[Source: python/yosoi/browser.py:1660](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L1660-L1670)

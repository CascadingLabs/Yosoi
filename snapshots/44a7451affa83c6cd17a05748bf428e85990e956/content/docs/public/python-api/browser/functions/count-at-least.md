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

[Source: python/yosoi/browser.py:1759](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L1759-L1769)

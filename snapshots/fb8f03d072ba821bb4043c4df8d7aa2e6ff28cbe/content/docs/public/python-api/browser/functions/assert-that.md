---
title: "assert_that"
description: "yosoi.browser.assert_that Python API reference."
order: 0
---

`yosoi.browser.assert_that`

```python
def assert_that(condition: Condition | ConditionExpectation) -> Assert:
```

Declare an immediate check of a DOM condition.

Args:
    condition: Raw DOM condition or ConditionExpectation wrapper.

Returns:
    Assert step; it checks once instead of waiting for readiness.

[Source: python/yosoi/browser.py:1686](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L1686-L1700)

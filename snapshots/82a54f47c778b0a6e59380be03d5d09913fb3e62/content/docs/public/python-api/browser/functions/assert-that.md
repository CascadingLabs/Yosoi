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

[Source: python/yosoi/browser.py:1587](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/browser.py#L1587-L1601)

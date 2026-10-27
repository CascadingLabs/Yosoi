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

[Source: python/yosoi/browser.py:1686](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L1686-L1700)

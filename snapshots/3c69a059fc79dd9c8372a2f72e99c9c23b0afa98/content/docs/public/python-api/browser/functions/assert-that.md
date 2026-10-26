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

[Source: python/yosoi/browser.py:1587](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L1587-L1601)

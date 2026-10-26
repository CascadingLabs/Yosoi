---
title: "until"
description: "yosoi.browser.until Python API reference."
order: 0
---

`yosoi.browser.until`

```python
def until(expectation: UntilExpectation | LocalRustAssertion, *, trigger: Step | None=None) -> UntilStep:
```

Declare an expectation wait around an optional one-shot trigger.

The trigger and wait share the execution deadline. Cancellation preserves execution
facts and does not roll back effects.

Args:
    expectation: Typed expectation or locally bound Contract assertion.
    trigger: Optional Click, EnterText, or JavaScript trigger.

Returns:
    UntilStep; observation begins before trigger dispatch.

[Source: python/yosoi/browser.py:1832](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L1832-L1851)

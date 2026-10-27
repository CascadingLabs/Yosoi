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

[Source: python/yosoi/browser.py:1832](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/browser.py#L1832-L1851)

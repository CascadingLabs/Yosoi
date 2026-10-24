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

[Source: python/yosoi/browser.py:1733](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/browser.py#L1733-L1752)

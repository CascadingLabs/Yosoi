---
title: "all_of"
description: "yosoi.browser.all_of Python API reference."
order: 0
---

`yosoi.browser.all_of`

```python
def all_of(expectations: Iterable[UntilExpectation | LocalRustAssertion]) -> AllExpectation:
```

Combine expectations so every child must be satisfied.

Args:
    expectations: Nonempty iterable copied into a tuple; local assertions retain
        bindings.

Returns:
    AllExpectation; Until validates tree size and depth.

[Source: python/yosoi/browser.py:1713](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/browser.py#L1713-L1730)

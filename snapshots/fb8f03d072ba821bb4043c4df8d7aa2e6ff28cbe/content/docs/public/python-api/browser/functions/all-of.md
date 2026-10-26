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

[Source: python/yosoi/browser.py:1812](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L1812-L1829)

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

[Source: python/yosoi/browser.py:1812](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/browser.py#L1812-L1829)

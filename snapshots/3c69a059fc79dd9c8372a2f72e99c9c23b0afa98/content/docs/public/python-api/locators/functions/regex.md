---
title: "regex"
description: "yosoi.locators.regex Python API reference."
order: 0
---

`yosoi.locators.regex`

```python
def regex(expression: str) -> Query:
```

Author decoded-text regular-expression range query intent without document I/O.

Args:
    expression: Authored expression in the selected query vocabulary.

Returns:
    Immutable Rust-checked intent, not acquired matches. Execution can still
    reject document capabilities, parser support, or resource limits.

Raises:
    LocatorError: Authored expression or supported syntax checks reject input.

[Source: python/yosoi/locators.py:819](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/locators.py#L819-L832)

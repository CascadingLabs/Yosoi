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

[Source: python/yosoi/locators.py:819](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/locators.py#L819-L832)

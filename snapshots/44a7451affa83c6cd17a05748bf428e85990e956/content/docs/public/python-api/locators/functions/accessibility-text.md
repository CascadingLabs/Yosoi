---
title: "accessibility_text"
description: "yosoi.locators.accessibility_text Python API reference."
order: 0
---

`yosoi.locators.accessibility_text`

```python
def accessibility_text(expression: str) -> Query:
```

Author accessibility node text query intent without document I/O.

Args:
    expression: Authored expression in the selected query vocabulary.

Returns:
    Immutable Rust-checked intent, not acquired matches. Execution can still
    reject document capabilities, parser support, or resource limits.

Raises:
    LocatorError: Authored expression or supported syntax checks reject input.

[Source: python/yosoi/locators.py:774](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/locators.py#L774-L787)

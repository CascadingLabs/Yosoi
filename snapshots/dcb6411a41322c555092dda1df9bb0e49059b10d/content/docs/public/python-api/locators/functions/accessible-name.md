---
title: "accessible_name"
description: "yosoi.locators.accessible_name Python API reference."
order: 0
---

`yosoi.locators.accessible_name`

```python
def accessible_name(expression: str) -> Query:
```

Author accessible node name query intent without document I/O.

Args:
    expression: Authored expression in the selected query vocabulary.

Returns:
    Immutable Rust-checked intent, not acquired matches. Execution can still
    reject document capabilities, parser support, or resource limits.

Raises:
    LocatorError: Authored expression or supported syntax checks reject input.

[Source: python/yosoi/locators.py:758](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/locators.py#L758-L771)

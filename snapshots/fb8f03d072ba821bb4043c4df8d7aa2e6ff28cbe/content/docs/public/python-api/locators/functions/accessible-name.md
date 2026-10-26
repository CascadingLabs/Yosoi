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

[Source: python/yosoi/locators.py:758](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L758-L771)

---
title: "tree_text_contains"
description: "yosoi.locators.tree_text_contains Python API reference."
order: 0
---

`yosoi.locators.tree_text_contains`

```python
def tree_text_contains(expression: str) -> Query:
```

Author tree descendant-text substring query intent without document I/O.

Args:
    expression: Authored expression in the selected query vocabulary.

Returns:
    Immutable Rust-checked intent, not acquired matches. Execution can still
    reject document capabilities, parser support, or resource limits.

Raises:
    LocatorError: Authored expression or supported syntax checks reject input.

[Source: python/yosoi/locators.py:694](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/locators.py#L694-L707)

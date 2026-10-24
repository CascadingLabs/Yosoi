---
title: "json_path"
description: "yosoi.locators.json_path Python API reference."
order: 0
---

`yosoi.locators.json_path`

```python
def json_path(expression: str) -> Query:
```

Author supported Rust JSONPath value query intent without document I/O.

Args:
    expression: Authored expression in the selected query vocabulary.

Returns:
    Immutable Rust-checked intent, not acquired matches. Execution can still
    reject document capabilities, parser support, or resource limits.

Raises:
    LocatorError: Authored expression or supported syntax checks reject input.

[Source: python/yosoi/locators.py:726](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/locators.py#L726-L739)

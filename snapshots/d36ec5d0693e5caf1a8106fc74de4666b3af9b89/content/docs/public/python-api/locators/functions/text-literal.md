---
title: "text_literal"
description: "yosoi.locators.text_literal Python API reference."
order: 0
---

`yosoi.locators.text_literal`

```python
def text_literal(expression: str) -> Query:
```

Author decoded-text literal range query intent without document I/O.

Args:
    expression: Authored expression in the selected query vocabulary.

Returns:
    Immutable Rust-checked intent, not acquired matches. Execution can still
    reject document capabilities, parser support, or resource limits.

Raises:
    LocatorError: Authored expression or supported syntax checks reject input.

[Source: python/yosoi/locators.py:803](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/locators.py#L803-L816)

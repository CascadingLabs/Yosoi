---
title: "output"
description: "yosoi.locators.output Python API reference."
order: 0
---

`yosoi.locators.output`

```python
def output(id: str | OutputId, locator: Locator) -> Output:
```

Name one explicit query and projection declaration.

Args:
    id: Authored output identity to validate and retain.
    locator: Query and projection selecting the finding evidence.

Returns:
    An output declaration; plan construction checks identity uniqueness.

Raises:
    LocatorError: The authored output identity is invalid.

[Source: python/yosoi/locators.py:646](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/locators.py#L646-L659)

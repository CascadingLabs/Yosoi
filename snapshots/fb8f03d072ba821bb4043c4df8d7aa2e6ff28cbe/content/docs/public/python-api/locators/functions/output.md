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

[Source: python/yosoi/locators.py:646](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/locators.py#L646-L659)

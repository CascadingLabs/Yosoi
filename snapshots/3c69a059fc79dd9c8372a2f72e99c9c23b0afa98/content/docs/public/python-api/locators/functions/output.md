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

[Source: python/yosoi/locators.py:646](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/locators.py#L646-L659)

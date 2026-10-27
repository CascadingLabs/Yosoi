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

[Source: python/yosoi/locators.py:646](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/locators.py#L646-L659)

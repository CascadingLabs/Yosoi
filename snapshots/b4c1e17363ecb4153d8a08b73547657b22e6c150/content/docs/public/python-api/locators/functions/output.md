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

[Source: python/yosoi/locators.py:646](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/locators.py#L646-L659)

---
title: "new"
description: "yosoi.request.new Python API reference."
order: 0
---

`yosoi.request.new`

```python
def new(target: str | WebTarget) -> PageRequest:
```

Author a page acquisition without URL validation or network I/O.

Args:
    target: Original string or WebTarget to validate during preparation.

Returns:
    A request with a fresh identity, using defaults until explicitly bound.

Raises:
    pydantic.ValidationError: The supplied target cannot form the authoring model.

[Source: python/yosoi/request.py:504](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/request.py#L504-L516)

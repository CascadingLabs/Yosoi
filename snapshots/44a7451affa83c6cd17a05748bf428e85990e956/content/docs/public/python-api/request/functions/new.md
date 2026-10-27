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

[Source: python/yosoi/request.py:516](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/request.py#L516-L528)

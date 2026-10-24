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

[Source: python/yosoi/request.py:516](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/request.py#L516-L528)

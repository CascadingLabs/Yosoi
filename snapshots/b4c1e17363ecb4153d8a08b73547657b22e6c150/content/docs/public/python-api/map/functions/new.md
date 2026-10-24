---
title: "new"
description: "yosoi.map.new Python API reference."
order: 0
---

`yosoi.map.new`

```python
def new(seed: str) -> MapRequest:
```

Author seed intent without URL validation or network I/O.

Args:
    seed: URL text to validate when the request is checked or sent.

Returns:
    A request using package defaults until bound to a policy.

Raises:
    pydantic.ValidationError: The seed is not a string.

[Source: python/yosoi/map.py:750](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/map.py#L750-L762)

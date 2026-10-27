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

[Source: python/yosoi/map.py:750](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/map.py#L750-L762)

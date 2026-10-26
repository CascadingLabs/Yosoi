---
title: "PositiveU16"
description: "yosoi.policy.PositiveU16 Python API reference."
order: 0
---

`yosoi.policy.PositiveU16`

```python
PositiveU16 = Annotated[int, Field(strict=True, gt=0, le=(1 << 16) - 1)]
```

Strict positive u16 integer; zero and numeric coercions are rejected.

[Source: python/yosoi/policy.py:43](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L43-L43)

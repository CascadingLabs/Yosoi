---
title: "PositiveU64"
description: "yosoi.policy.PositiveU64 Python API reference."
order: 0
---

`yosoi.policy.PositiveU64`

```python
PositiveU64 = Annotated[int, Field(strict=True, gt=0, le=(1 << 64) - 1)]
```

Strict positive u64 integer; zero and numeric coercions are rejected.

[Source: python/yosoi/policy.py:39](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L39-L39)

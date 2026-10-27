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

[Source: python/yosoi/policy.py:47](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L47-L47)

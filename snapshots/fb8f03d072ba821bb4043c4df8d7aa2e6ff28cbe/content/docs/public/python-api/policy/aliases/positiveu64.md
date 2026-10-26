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

[Source: python/yosoi/policy.py:47](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L47-L47)

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

[Source: python/yosoi/policy.py:47](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/policy.py#L47-L47)

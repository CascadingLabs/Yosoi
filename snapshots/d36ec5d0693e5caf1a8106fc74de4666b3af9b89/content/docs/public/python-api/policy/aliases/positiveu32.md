---
title: "PositiveU32"
description: "yosoi.policy.PositiveU32 Python API reference."
order: 0
---

`yosoi.policy.PositiveU32`

```python
PositiveU32 = Annotated[int, Field(strict=True, gt=0, le=(1 << 32) - 1)]
```

Strict positive u32 integer; zero and numeric coercions are rejected.

[Source: python/yosoi/policy.py:45](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/policy.py#L45-L45)

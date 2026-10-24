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

[Source: python/yosoi/policy.py:35](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L35-L35)

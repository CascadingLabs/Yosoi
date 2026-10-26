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

[Source: python/yosoi/policy.py:37](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/policy.py#L37-L37)

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

[Source: python/yosoi/policy.py:39](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L39-L39)

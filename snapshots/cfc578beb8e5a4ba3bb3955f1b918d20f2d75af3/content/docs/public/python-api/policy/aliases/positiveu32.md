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

[Source: python/yosoi/policy.py:37](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L37-L37)

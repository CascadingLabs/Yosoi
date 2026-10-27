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

[Source: python/yosoi/policy.py:43](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L43-L43)

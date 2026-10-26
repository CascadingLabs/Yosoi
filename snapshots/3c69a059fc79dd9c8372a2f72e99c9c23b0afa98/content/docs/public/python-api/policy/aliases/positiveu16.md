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

[Source: python/yosoi/policy.py:35](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/policy.py#L35-L35)

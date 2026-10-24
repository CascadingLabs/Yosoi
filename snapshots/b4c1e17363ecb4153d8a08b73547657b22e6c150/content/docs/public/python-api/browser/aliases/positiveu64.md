---
title: "PositiveU64"
description: "yosoi.browser.PositiveU64 Python API reference."
order: 0
---

`yosoi.browser.PositiveU64`

```python
PositiveU64 = Annotated[int, Field(strict=True, gt=0, le=(1 << 64) - 1)]
```

Strict integer from 1 through 2**64 - 1 for positive browser values.

Zero, booleans, floating-point values, and numeric strings are rejected rather
than coerced. Units belong to the consuming parameter; this alias alone does
not imply milliseconds, bytes, or an existing browser object.

[Source: python/yosoi/browser.py:53](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/browser.py#L53-L53)

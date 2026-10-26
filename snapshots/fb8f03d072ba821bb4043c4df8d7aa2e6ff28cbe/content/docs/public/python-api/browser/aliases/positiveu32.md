---
title: "PositiveU32"
description: "yosoi.browser.PositiveU32 Python API reference."
order: 0
---

`yosoi.browser.PositiveU32`

```python
PositiveU32 = Annotated[int, Field(strict=True, gt=0, le=(1 << 32) - 1)]
```

Strict integer from 1 through 2**32 - 1 for positive browser values.

Zero, booleans, floating-point values, and numeric strings are rejected. This
alias checks numeric range, not whether a referenced object exists.

[Source: python/yosoi/browser.py:49](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L49-L49)

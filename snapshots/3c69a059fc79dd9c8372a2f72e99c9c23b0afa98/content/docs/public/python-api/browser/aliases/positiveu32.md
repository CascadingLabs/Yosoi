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

[Source: python/yosoi/browser.py:46](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L46-L46)

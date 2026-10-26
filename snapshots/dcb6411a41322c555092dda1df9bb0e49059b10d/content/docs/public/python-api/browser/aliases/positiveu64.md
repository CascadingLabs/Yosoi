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

[Source: python/yosoi/browser.py:56](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/browser.py#L56-L56)

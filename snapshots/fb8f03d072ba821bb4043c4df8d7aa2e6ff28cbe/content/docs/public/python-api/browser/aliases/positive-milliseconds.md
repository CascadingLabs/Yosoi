---
title: "PositiveMilliseconds"
description: "yosoi.browser.PositiveMilliseconds Python API reference."
order: 0
---

`yosoi.browser.PositiveMilliseconds`

```python
PositiveMilliseconds = Annotated[int, Field(strict=True, gt=0, le=((1 << 64) - 1) // 1000)]
```

Positive integer milliseconds whose microsecond conversion fits in u64.

Accepts 1 through (2**64 - 1) // 1_000 without numeric coercion. This validates
the representable duration range; operation-specific deadlines still apply.

[Source: python/yosoi/browser.py:64](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/browser.py#L64-L66)

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

[Source: python/yosoi/browser.py:61](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/browser.py#L61-L63)

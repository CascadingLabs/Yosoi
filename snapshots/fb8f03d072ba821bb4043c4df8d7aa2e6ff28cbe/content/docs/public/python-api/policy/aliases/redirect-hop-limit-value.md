---
title: "RedirectHopLimitValue"
description: "yosoi.policy.RedirectHopLimitValue Python API reference."
order: 0
---

`yosoi.policy.RedirectHopLimitValue`

```python
RedirectHopLimitValue = Annotated[int, Field(strict=True), AfterValidator(_scalar_validator(RedirectHopLimit))]
```

Strict positive u32 Direct HTTP redirect-transition bound validated by Rust.

[Source: python/yosoi/policy.py:154](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L154-L156)

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

[Source: python/yosoi/policy.py:142](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L142-L144)

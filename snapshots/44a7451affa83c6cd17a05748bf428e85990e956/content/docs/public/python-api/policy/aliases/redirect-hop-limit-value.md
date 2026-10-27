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

[Source: python/yosoi/policy.py:154](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L154-L156)

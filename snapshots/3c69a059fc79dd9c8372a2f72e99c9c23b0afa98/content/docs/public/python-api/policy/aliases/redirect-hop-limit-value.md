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

[Source: python/yosoi/policy.py:142](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/policy.py#L142-L144)

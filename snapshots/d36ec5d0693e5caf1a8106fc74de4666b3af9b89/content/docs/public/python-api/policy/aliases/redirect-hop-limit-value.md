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

[Source: python/yosoi/policy.py:154](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/policy.py#L154-L156)

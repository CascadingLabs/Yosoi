---
title: "StepLimitValue"
description: "yosoi.policy.StepLimitValue Python API reference."
order: 0
---

`yosoi.policy.StepLimitValue`

```python
StepLimitValue = Annotated[int, Field(strict=True), AfterValidator(_scalar_validator(StepLimit))]
```

Strict positive u32 query/depth counter validated by Rust.

[Source: python/yosoi/policy.py:114](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L114-L116)

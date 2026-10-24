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

[Source: python/yosoi/policy.py:114](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L114-L116)

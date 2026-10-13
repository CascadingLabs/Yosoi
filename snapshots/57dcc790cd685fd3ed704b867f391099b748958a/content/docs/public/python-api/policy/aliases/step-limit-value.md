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

[Source: python/yosoi/policy.py:114](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L114-L116)

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

[Source: python/yosoi/policy.py:126](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L126-L128)

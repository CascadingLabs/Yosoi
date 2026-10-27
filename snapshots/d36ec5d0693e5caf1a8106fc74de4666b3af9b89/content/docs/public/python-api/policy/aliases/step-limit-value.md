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

[Source: python/yosoi/policy.py:126](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/policy.py#L126-L128)

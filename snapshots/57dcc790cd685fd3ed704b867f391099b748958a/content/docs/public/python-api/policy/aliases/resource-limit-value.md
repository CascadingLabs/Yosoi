---
title: "ResourceLimitValue"
description: "yosoi.policy.ResourceLimitValue Python API reference."
order: 0
---

`yosoi.policy.ResourceLimitValue`

```python
ResourceLimitValue = Annotated[int, Field(strict=True), AfterValidator(_scalar_validator(ResourceLimit))]
```

Strict positive addressable u32 resource-count bound validated by Rust.

[Source: python/yosoi/policy.py:126](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L126-L128)

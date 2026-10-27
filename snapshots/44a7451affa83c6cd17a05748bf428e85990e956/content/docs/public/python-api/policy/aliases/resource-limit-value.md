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

[Source: python/yosoi/policy.py:138](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L138-L140)

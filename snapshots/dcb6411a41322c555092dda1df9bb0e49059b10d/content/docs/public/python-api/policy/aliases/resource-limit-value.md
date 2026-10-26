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

[Source: python/yosoi/policy.py:138](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L138-L140)

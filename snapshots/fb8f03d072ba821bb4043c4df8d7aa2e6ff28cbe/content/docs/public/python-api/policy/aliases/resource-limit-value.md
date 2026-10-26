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

[Source: python/yosoi/policy.py:138](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L138-L140)

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

[Source: python/yosoi/policy.py:126](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L126-L128)

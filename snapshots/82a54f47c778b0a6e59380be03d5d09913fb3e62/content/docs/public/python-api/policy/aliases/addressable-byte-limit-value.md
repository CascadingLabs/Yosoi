---
title: "AddressableByteLimitValue"
description: "yosoi.policy.AddressableByteLimitValue Python API reference."
order: 0
---

`yosoi.policy.AddressableByteLimitValue`

```python
AddressableByteLimitValue = Annotated[int, Field(strict=True), AfterValidator(_scalar_validator(AddressableByteLimit))]
```

Strict positive u64 byte limit checked by Rust to fit platform address size.

[Source: python/yosoi/policy.py:118](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L118-L120)

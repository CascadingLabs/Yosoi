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

[Source: python/yosoi/policy.py:118](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L118-L120)

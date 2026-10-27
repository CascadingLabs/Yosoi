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

[Source: python/yosoi/policy.py:130](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L130-L132)

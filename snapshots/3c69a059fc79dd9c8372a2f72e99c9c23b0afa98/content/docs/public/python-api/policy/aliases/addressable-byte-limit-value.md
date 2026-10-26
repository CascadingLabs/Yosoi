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

[Source: python/yosoi/policy.py:118](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/policy.py#L118-L120)

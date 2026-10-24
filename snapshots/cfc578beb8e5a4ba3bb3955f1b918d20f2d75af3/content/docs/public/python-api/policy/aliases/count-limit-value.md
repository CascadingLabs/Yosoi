---
title: "CountLimitValue"
description: "yosoi.policy.CountLimitValue Python API reference."
order: 0
---

`yosoi.policy.CountLimitValue`

```python
CountLimitValue = Annotated[int, Field(strict=True), AfterValidator(_scalar_validator(CountLimit))]
```

Strict positive u64 policy count validated by Rust; zero never means unlimited.

[Source: python/yosoi/policy.py:110](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L110-L112)

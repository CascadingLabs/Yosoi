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

[Source: python/yosoi/policy.py:110](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L110-L112)

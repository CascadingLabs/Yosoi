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

[Source: python/yosoi/policy.py:122](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L122-L124)

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

[Source: python/yosoi/policy.py:122](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L122-L124)

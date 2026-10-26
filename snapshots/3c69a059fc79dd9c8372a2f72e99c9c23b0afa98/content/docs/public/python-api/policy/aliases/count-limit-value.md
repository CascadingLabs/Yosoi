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

[Source: python/yosoi/policy.py:110](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/policy.py#L110-L112)

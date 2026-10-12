---
title: "EventLimitValue"
description: "yosoi.policy.EventLimitValue Python API reference."
order: 0
---

`yosoi.policy.EventLimitValue`

```python
EventLimitValue = Annotated[int, Field(strict=True), AfterValidator(_scalar_validator(EventLimit))]
```

Strict positive addressable browser event count validated by Rust.

[Source: python/yosoi/policy.py:122](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L122-L124)

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

[Source: python/yosoi/policy.py:122](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L122-L124)

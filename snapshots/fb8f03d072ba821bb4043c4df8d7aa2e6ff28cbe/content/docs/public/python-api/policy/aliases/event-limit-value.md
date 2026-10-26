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

[Source: python/yosoi/policy.py:134](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L134-L136)

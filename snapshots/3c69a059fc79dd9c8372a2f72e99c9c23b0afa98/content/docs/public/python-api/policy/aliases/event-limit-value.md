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

[Source: python/yosoi/policy.py:122](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/policy.py#L122-L124)

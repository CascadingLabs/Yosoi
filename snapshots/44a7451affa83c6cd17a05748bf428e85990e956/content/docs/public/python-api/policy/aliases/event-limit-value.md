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

[Source: python/yosoi/policy.py:134](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L134-L136)

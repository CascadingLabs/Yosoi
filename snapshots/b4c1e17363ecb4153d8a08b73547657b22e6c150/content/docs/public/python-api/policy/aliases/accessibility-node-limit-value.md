---
title: "AccessibilityNodeLimitValue"
description: "yosoi.policy.AccessibilityNodeLimitValue Python API reference."
order: 0
---

`yosoi.policy.AccessibilityNodeLimitValue`

```python
AccessibilityNodeLimitValue = Annotated[int, Field(strict=True), AfterValidator(_scalar_validator(AccessibilityNodeLimit))]
```

Strict positive addressable u32 accessibility-node bound validated by Rust.

[Source: python/yosoi/policy.py:130](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L130-L134)

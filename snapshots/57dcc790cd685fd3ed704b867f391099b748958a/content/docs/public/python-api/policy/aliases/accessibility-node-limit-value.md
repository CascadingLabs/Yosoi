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

[Source: python/yosoi/policy.py:130](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/policy.py#L130-L134)

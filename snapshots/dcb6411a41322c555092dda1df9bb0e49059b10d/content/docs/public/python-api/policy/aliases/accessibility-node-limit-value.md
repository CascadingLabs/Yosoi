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

[Source: python/yosoi/policy.py:142](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L142-L146)

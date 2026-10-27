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

[Source: python/yosoi/policy.py:142](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L142-L146)

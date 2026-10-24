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

[Source: python/yosoi/policy.py:130](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L130-L134)

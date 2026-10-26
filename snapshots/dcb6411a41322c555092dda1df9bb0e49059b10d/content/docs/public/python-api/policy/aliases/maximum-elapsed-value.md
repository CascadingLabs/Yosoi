---
title: "MaximumElapsedValue"
description: "yosoi.policy.MaximumElapsedValue Python API reference."
order: 0
---

`yosoi.policy.MaximumElapsedValue`

```python
MaximumElapsedValue = Annotated[int, Field(strict=True), AfterValidator(_scalar_validator(MaximumElapsed))]
```

Strict positive u64 elapsed budget in microseconds. Conversion to a platform
capture deadline is checked separately.

[Source: python/yosoi/policy.py:148](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L148-L150)

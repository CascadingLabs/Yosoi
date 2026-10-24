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

[Source: python/yosoi/policy.py:136](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/policy.py#L136-L138)

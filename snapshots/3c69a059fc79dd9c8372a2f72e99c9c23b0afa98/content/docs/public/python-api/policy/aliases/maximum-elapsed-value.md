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

[Source: python/yosoi/policy.py:136](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/policy.py#L136-L138)

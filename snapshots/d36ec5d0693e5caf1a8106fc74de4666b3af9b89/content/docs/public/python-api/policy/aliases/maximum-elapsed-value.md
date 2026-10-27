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

[Source: python/yosoi/policy.py:148](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/policy.py#L148-L150)

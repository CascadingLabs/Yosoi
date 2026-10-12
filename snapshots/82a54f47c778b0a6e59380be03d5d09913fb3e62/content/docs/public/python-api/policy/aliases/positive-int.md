---
title: "PositiveInt"
description: "yosoi.policy.PositiveInt Python API reference."
order: 0
---

`yosoi.policy.PositiveInt`

```python
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
```

Strict positive Python integer. Native policy validation applies
operation-specific width and plan constraints.

[Source: python/yosoi/policy.py:41](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L41-L41)

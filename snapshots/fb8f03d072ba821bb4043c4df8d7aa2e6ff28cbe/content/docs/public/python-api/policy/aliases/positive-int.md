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

[Source: python/yosoi/policy.py:49](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/policy.py#L49-L49)

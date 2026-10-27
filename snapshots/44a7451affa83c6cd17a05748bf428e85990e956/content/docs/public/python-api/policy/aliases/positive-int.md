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

[Source: python/yosoi/policy.py:49](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L49-L49)

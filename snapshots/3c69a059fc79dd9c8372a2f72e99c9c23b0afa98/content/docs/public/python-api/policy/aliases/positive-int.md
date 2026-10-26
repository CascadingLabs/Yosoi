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

[Source: python/yosoi/policy.py:41](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/policy.py#L41-L41)

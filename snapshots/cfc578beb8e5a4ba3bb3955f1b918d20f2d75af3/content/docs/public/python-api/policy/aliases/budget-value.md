---
title: "BudgetValue"
description: "yosoi.policy.BudgetValue Python API reference."
order: 0
---

`yosoi.policy.BudgetValue`

```python
BudgetValue = Annotated[int, Field(strict=True), AfterValidator(_scalar_validator(Budget))]
```

Strict positive u32 Map budget validated by Rust; zero is not an unlimited
setting.

[Source: python/yosoi/policy.py:146](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/policy.py#L146-L148)

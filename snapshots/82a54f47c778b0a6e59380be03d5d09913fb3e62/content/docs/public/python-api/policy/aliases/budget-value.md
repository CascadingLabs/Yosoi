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

[Source: python/yosoi/policy.py:146](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/policy.py#L146-L148)

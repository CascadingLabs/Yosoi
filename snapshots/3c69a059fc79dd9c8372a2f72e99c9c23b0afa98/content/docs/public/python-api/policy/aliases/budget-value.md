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

[Source: python/yosoi/policy.py:146](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/policy.py#L146-L148)

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

[Source: python/yosoi/policy.py:158](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/policy.py#L158-L160)

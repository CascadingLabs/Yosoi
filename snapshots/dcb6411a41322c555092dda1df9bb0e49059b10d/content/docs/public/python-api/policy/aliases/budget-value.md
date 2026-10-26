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

[Source: python/yosoi/policy.py:158](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/policy.py#L158-L160)

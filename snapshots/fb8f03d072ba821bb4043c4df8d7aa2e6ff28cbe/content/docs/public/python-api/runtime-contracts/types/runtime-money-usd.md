---
title: "RuntimeMoneyUsd"
description: "yosoi.runtime_contracts.RuntimeMoneyUsd Python API reference."
order: 0
---

`yosoi.runtime_contracts.RuntimeMoneyUsd`

```python
class RuntimeMoneyUsd(ImmutableModel):
```

Carry a USD amount accepted by runtime Contract validation.

Attributes:
    type: Wire discriminator identifying USD money.
    value: Typed Money value retaining its currency and minor-unit amount.

[Source: python/yosoi/runtime_contracts.py:89](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/runtime_contracts.py#L89-L98)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
type: Literal['money_usd']
value: Money
```

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

[Source: python/yosoi/runtime_contracts.py:89](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L89-L98)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
type: Literal['money_usd']
value: Money
```

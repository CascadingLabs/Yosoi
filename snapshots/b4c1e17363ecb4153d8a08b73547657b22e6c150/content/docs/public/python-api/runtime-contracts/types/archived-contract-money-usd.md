---
title: "ArchivedContractMoneyUsd"
description: "yosoi.runtime_contracts.ArchivedContractMoneyUsd Python API reference."
order: 0
---

`yosoi.runtime_contracts.ArchivedContractMoneyUsd`

```python
class ArchivedContractMoneyUsd(ImmutableModel):
```

Store USD money as a portable signed minor-unit amount.

Attributes:
    type: Wire discriminator for archived USD values.
    minor_units: Signed 64-bit count of cents; the DTO bounds the integer without
        revalidating a Contract.

[Source: python/yosoi/runtime_contracts.py:223](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/runtime_contracts.py#L223-L235)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
type: Literal['money_usd']
minor_units: Annotated[int, Field(strict=True, ge=-2 ** 63, le=2 ** 63 - 1, repr=False)]
```

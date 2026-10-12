---
title: "ArchivedContractMoneyUsd"
description: "yosoi.contracts.ArchivedContractMoneyUsd Python API reference."
order: 0
---

`yosoi.contracts.ArchivedContractMoneyUsd`

```python
ArchivedContractMoneyUsd = _runtime_contracts.ArchivedContractMoneyUsd
```

Store USD money as a portable signed minor-unit amount.

Attributes:
    type: Wire discriminator for archived USD values.
    minor_units: Signed 64-bit count of cents; the DTO bounds the integer without
        revalidating a Contract.

[Source: python/yosoi/contracts.py:991](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/contracts.py#L991-L991)

[Definition](/yosoi/python-api/runtime-contracts/types/archived-contract-money-usd/)

[Source: python/yosoi/runtime_contracts.py:223](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/runtime_contracts.py#L223-L235)

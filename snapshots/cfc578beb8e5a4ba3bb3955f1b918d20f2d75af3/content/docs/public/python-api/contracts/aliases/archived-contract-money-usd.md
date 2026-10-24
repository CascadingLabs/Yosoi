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

[Source: python/yosoi/contracts.py:1625](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/contracts.py#L1625-L1625)

[Definition](/yosoi/python-api/runtime-contracts/types/archived-contract-money-usd/)

[Source: python/yosoi/runtime_contracts.py:223](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L223-L235)

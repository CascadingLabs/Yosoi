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

[Source: python/yosoi/contracts.py:1625](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/contracts.py#L1625-L1625)

[Definition](/yosoi/python-api/runtime-contracts/types/archived-contract-money-usd/)

[Source: python/yosoi/runtime_contracts.py:223](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/runtime_contracts.py#L223-L235)

---
title: "ArchivedContractValue"
description: "yosoi.runtime_contracts.ArchivedContractValue Python API reference."
order: 0
---

`yosoi.runtime_contracts.ArchivedContractValue`

```python
type ArchivedContractValue = Annotated[ArchivedContractString | ArchivedContractMoneyUsd, Field(discriminator='type')]
```

Portable string or signed USD minor-unit value tagged by type.

[Source: python/yosoi/runtime_contracts.py:238](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L238-L240)

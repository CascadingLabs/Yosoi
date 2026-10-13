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

[Source: python/yosoi/runtime_contracts.py:238](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L238-L240)

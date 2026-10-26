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

[Source: python/yosoi/runtime_contracts.py:238](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/runtime_contracts.py#L238-L240)

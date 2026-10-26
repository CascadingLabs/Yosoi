---
title: "ContractSchemaFailure"
description: "yosoi.runtime_contracts.ContractSchemaFailure Python API reference."
order: 0
---

`yosoi.runtime_contracts.ContractSchemaFailure`

```python
type ContractSchemaFailure = Annotated[_ContractSchemaErrorUnit | _ContractSchemaErrorUnsupportedVersion | _ContractSchemaErrorField, Field(discriminator='variant')]
```

Structured Rust schema error tagged by its variant and typed details.

[Source: python/yosoi/runtime_contracts.py:584](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/runtime_contracts.py#L584-L589)

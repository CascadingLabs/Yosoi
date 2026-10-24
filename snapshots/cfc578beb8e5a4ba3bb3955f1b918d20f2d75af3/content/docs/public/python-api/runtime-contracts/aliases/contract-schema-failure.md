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

[Source: python/yosoi/runtime_contracts.py:584](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L584-L589)

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

[Source: python/yosoi/runtime_contracts.py:552](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L552-L557)

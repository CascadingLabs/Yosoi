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

[Source: python/yosoi/runtime_contracts.py:552](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/runtime_contracts.py#L552-L557)

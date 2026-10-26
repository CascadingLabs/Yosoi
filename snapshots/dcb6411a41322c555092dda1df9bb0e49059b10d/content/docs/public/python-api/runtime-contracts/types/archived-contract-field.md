---
title: "ArchivedContractField"
description: "yosoi.runtime_contracts.ArchivedContractField Python API reference."
order: 0
---

`yosoi.runtime_contracts.ArchivedContractField`

```python
class ArchivedContractField(ImmutableModel):
```

Pair an archived schema field ID with its accepted value.

Attributes:
    id: Identity of the field in the archive schema.
    value: Portable value with an explicit cardinality discriminator.

[Source: python/yosoi/runtime_contracts.py:234](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L234-L243)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: FieldId
value: ArchivedContractFieldValue = Field(repr=False)
```

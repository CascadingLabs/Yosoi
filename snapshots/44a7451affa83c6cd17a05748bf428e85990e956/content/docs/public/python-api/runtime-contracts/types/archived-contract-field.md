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

[Source: python/yosoi/runtime_contracts.py:234](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/runtime_contracts.py#L234-L243)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: FieldId
value: ArchivedContractFieldValue = Field(repr=False)
```

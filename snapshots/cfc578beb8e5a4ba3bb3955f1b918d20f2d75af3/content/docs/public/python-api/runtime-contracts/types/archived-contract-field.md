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

[Source: python/yosoi/runtime_contracts.py:266](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L266-L275)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: FieldId
value: ArchivedContractFieldValue = Field(repr=False)
```

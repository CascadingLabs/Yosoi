---
title: "ArchivedContractCandidateField"
description: "yosoi.runtime_contracts.ArchivedContractCandidateField Python API reference."
order: 0
---

`yosoi.runtime_contracts.ArchivedContractCandidateField`

```python
class ArchivedContractCandidateField(ImmutableModel):
```

Store portable evidence for one archived candidate field.

Attributes:
    id: Schema field identity.
    evidence: Original findings retained for audit or later inspection.

[Source: python/yosoi/runtime_contracts.py:199](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L199-L208)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: FieldId
evidence: tuple[Finding, ...] = Field(repr=False)
```

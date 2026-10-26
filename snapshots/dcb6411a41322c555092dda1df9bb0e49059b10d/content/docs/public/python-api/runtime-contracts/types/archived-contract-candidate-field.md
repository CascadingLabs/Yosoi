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

[Source: python/yosoi/runtime_contracts.py:184](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/runtime_contracts.py#L184-L193)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: FieldId
evidence: tuple[Finding, ...] = Field(repr=False)
```

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

[Source: python/yosoi/runtime_contracts.py:184](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/runtime_contracts.py#L184-L193)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: FieldId
evidence: tuple[Finding, ...] = Field(repr=False)
```

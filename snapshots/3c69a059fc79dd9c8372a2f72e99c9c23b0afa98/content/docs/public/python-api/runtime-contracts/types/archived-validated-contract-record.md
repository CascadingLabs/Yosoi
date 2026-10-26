---
title: "ArchivedValidatedContractRecord"
description: "yosoi.runtime_contracts.ArchivedValidatedContractRecord Python API reference."
order: 0
---

`yosoi.runtime_contracts.ArchivedValidatedContractRecord`

```python
class ArchivedValidatedContractRecord(ImmutableModel):
```

Retain accepted portable values together with source evidence.

Attributes:
    document_id: Identity of the source document.
    region: Grouping region lineage, or None for an ungrouped record.
    fields: Accepted field values in the portable archive representation.
    evidence: Original per-field findings accompanying the accepted values.

[Source: python/yosoi/runtime_contracts.py:278](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/runtime_contracts.py#L278-L291)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document_id: str
region: RegionLineage | None = None
fields: tuple[ArchivedContractField, ...] = Field(repr=False)
evidence: tuple[ArchivedContractCandidateField, ...] = Field(repr=False)
```

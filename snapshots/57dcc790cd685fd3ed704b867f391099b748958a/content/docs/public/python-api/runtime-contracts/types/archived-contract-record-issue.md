---
title: "ArchivedContractRecordIssue"
description: "yosoi.runtime_contracts.ArchivedContractRecordIssue Python API reference."
order: 0
---

`yosoi.runtime_contracts.ArchivedContractRecordIssue`

```python
class ArchivedContractRecordIssue(ImmutableModel):
```

Retain a rejected portable candidate with its field issues.

Attributes:
    document_id: Identity of the source document.
    region: Grouping region lineage, or None for an ungrouped candidate.
    candidate_fields: Original findings grouped by schema field ID.
    fields: Reasons the candidate did not become an accepted record.

[Source: python/yosoi/runtime_contracts.py:294](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/runtime_contracts.py#L294-L307)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document_id: str
region: RegionLineage | None = None
candidate_fields: tuple[ArchivedContractCandidateField, ...] = Field(repr=False)
fields: tuple[FieldIssue, ...] = Field(repr=False)
```

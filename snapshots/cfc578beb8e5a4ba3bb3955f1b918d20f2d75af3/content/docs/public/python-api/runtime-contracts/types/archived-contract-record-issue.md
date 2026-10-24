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

[Source: python/yosoi/runtime_contracts.py:294](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/runtime_contracts.py#L294-L307)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document_id: str
region: RegionLineage | None = None
candidate_fields: tuple[ArchivedContractCandidateField, ...] = Field(repr=False)
fields: tuple[FieldIssue, ...] = Field(repr=False)
```

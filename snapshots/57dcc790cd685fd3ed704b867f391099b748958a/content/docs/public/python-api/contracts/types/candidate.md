---
title: "Candidate"
description: "yosoi.contracts.Candidate Python API reference."
order: 0
---

`yosoi.contracts.Candidate`

```python
class Candidate(ImmutableModel):
```

Grouping metadata for generated typed candidate records.

Attributes:
    document_id: Document supplying candidate findings.
    region: Repeated-region lineage, or None for page grouping. Generated subclasses
        add named CandidateField members.

[Source: python/yosoi/contracts.py:326](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L326-L336)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document_id: str
region: RegionLineage | None = None
```

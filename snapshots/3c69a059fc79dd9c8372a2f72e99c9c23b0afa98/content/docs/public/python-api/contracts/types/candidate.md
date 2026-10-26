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

[Source: python/yosoi/contracts.py:372](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L372-L402)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document_id: str
region: RegionLineage | None = None
```

## Methods

### fields

```python
@property
def fields(self) -> dict[str, CandidateField]:
```

Return field evidence keyed by authored native field ID.

The mapping is a fresh dictionary; its frozen CandidateField values retain
ordered findings without copying projected source content.

[Source: python/yosoi/contracts.py:385](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L385-L395)

### field

```python
def field(self, field_id: str | FieldId) -> CandidateField:
```

Return one candidate field by its authored native field ID.

[Source: python/yosoi/contracts.py:397](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/contracts.py#L397-L402)

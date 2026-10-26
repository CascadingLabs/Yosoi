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

[Source: python/yosoi/contracts.py:327](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L327-L357)

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

[Source: python/yosoi/contracts.py:340](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L340-L350)

### field

```python
def field(self, field_id: str | FieldId) -> CandidateField:
```

Return one candidate field by its authored native field ID.

[Source: python/yosoi/contracts.py:352](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/contracts.py#L352-L357)

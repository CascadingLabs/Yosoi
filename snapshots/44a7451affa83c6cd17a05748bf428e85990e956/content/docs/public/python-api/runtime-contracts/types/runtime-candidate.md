---
title: "RuntimeCandidate"
description: "yosoi.runtime_contracts.RuntimeCandidate Python API reference."
order: 0
---

`yosoi.runtime_contracts.RuntimeCandidate`

```python
class RuntimeCandidate(ImmutableModel):
```

Retain raw findings for every field of one runtime candidate.

Findings have not yet passed cardinality or value conversion checks.

Attributes:
    document_id: Identity of the document whose evidence was grouped.
    region: Grouping region lineage, or None for an ungrouped candidate.
    fields: Read-only field-to-findings mapping, including empty tuples for missing
        evidence.

[Source: python/yosoi/runtime_contracts.py:36](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/runtime_contracts.py#L36-L73)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document_id: str
region: RegionLineage | None = None
fields: Mapping[str, tuple[Finding, ...]]
```

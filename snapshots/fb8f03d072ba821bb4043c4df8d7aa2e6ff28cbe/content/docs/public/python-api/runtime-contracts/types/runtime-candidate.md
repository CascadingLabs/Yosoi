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

[Source: python/yosoi/runtime_contracts.py:37](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/runtime_contracts.py#L37-L74)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document_id: str
region: RegionLineage | None = None
fields: Mapping[str, tuple[Finding, ...]]
```

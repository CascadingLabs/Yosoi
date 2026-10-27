---
title: "LocateResult"
description: "yosoi.outcomes.LocateResult Python API reference."
order: 0
---

`yosoi.outcomes.LocateResult`

```python
class LocateResult(ImmutableModel):
```

Nonempty matched regions or findings in deterministic global order.

Attributes:
    document_id: Shared identity checked against every finding.
    regions: Unique retained region lineage, including regions with no projected
        findings.
    findings: Findings in strictly increasing global order, each referring only to a
        known parent region.

[Source: python/yosoi/outcomes.py:839](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/outcomes.py#L839-L914)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document_id: DocumentId
regions: tuple[RegionLineage, ...]
findings: tuple[Finding, ...]
```

## Methods

### try_new

```python
@classmethod
def try_new(cls, document_id: DocumentId, findings: tuple[Finding, ...]) -> Self:
```

Create an ordered result, deriving regions from finding lineage.

Args:
    document_id: Shared identity required for every finding.
    findings: Nonempty findings with strictly increasing global order.

Returns:
    A validated result with unique parent regions derived from the findings.

Raises:
    LocatorError: Findings are empty, belong to another document, or violate
        deterministic order or supplied wire structure.

[Source: python/yosoi/outcomes.py:863](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/outcomes.py#L863-L882)

### try_new_with_regions

```python
@classmethod
def try_new_with_regions(cls, document_id: DocumentId, regions: tuple[RegionLineage, ...], findings: tuple[Finding, ...]) -> Self:
```

Create a result with explicit matched regions and ordered findings.

Args:
    document_id: Shared identity required for every finding.
    regions: Unique matched regions, including those without projected findings.
    findings: Findings with strictly increasing order and known parent lineage.

Returns:
    A validated result; at least one supplied collection must be nonempty.

Raises:
    LocatorError: Collections are empty, lineage is duplicated or unknown,
        document identities differ, or finding order or wire structure is
        invalid.

[Source: python/yosoi/outcomes.py:885](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/outcomes.py#L885-L914)

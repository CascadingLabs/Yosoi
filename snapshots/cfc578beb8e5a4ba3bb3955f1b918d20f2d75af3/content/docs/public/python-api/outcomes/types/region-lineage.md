---
title: "RegionLineage"
description: "yosoi.outcomes.RegionLineage Python API reference."
order: 0
---

`yosoi.outcomes.RegionLineage`

```python
class RegionLineage(ImmutableModel):
```

Parent repeated-region identity and location for a finding.

Attributes:
    region_id: Authored repeated-region identifier.
    region_ordinal: Recorded region ordinal, preserved without renumbering.
    coordinate: Native location of the repeated parent region.

[Source: python/yosoi/outcomes.py:700](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/outcomes.py#L700-L744)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
region_id: RegionId
region_ordinal: U64
coordinate: NativeCoordinate
```

## Methods

### new

```python
@classmethod
def new(cls, region_id: RegionId, region_ordinal: int, coordinate: NativeCoordinate) -> Self:
```

Create parent-region lineage while validating wire structure.

Args:
    region_id: Authored region identifier.
    region_ordinal: Recorded unsigned ordinal, preserved without renumbering.
    coordinate: Native parent-region location.

Returns:
    Lineage without verifying a region plan or resolving document coordinates.

Raises:
    LocatorError: Supplied values cannot form valid Rust lineage data.

[Source: python/yosoi/outcomes.py:720](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/outcomes.py#L720-L744)

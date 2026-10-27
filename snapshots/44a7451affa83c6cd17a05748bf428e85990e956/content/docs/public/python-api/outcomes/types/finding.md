---
title: "Finding"
description: "yosoi.outcomes.Finding Python API reference."
order: 0
---

`yosoi.outcomes.Finding`

```python
class Finding(ImmutableModel):
```

An ordered locator finding with projection and completeness evidence.

Attributes:
    document_id: Document identity to which this evidence belongs.
    output_id: Authored output identity producing the finding.
    order: Global deterministic order; results require strictly increasing values.
    coordinate: Native evidence location without a copy of document contents.
    projected: Typed projection, serialized under the Rust field name value. Node
        projections must agree with the finding document and coordinate.
    completeness: Coverage claim inherited from evidence, not independently verified
        here.
    parent_region: Repeated-region lineage, or None for findings without a parent.

[Source: python/yosoi/outcomes.py:747](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/outcomes.py#L747-L836)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document_id: DocumentId
output_id: OutputId
order: U64
coordinate: NativeCoordinate
projected: ProjectedValue = Field(alias='value')
completeness: Completeness
parent_region: RegionLineage | None = None
```

## Methods

### try_new

```python
@classmethod
def try_new(cls, document_id: DocumentId, output_id: OutputId, order: int, coordinate: NativeCoordinate, projected: ProjectedValue, completeness: Completeness, parent_region: RegionLineage | None=None) -> Self:
```

Create a finding and check any projected node-reference identity.

Args:
    document_id: Identity of the source evidence document.
    output_id: Authored output identifier producing this finding.
    order: Deterministic global order for the finding.
    coordinate: Native evidence location.
    projected: Typed projected value; a node reference must match the finding
        document and coordinate.
    completeness: Supplied evidence coverage claim, not independently verified.
    parent_region: Optional lineage for repeated-region evidence.

Returns:
    A typed finding without fetching or retaining document contents.

Raises:
    LocatorError: Projected node identity disagrees or wire data is invalid.

[Source: python/yosoi/outcomes.py:779](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/outcomes.py#L779-L823)

### value

```python
@property
def value(self) -> str | JsonValue | NodeReference:
```

Return projection content without its structural projection wrapper.

Text-with-captures yields full text; attributes yield decoded attribute text.
Use projected to retain capture names, attribute names, and variant identity.

[Source: python/yosoi/outcomes.py:826](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/outcomes.py#L826-L836)

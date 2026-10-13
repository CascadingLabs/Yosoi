---
title: "Region"
description: "yosoi.locators.Region Python API reference."
order: 0
---

`yosoi.locators.Region`

```python
class Region(ImmutableModel):
```

One authored repeated-region query and its lineage identity.

Attributes:
    id: Unique authored repeated-region identity.
    query: Root query without an existing parent region; nested regions are
        unsupported.

[Source: python/yosoi/locators.py:474](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/locators.py#L474-L502)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: RegionId
query: Query
```

## Methods

### find

```python
def find(self, query: Query) -> Query:
```

Scope a query within each match of this repeated-region root.

Args:
    query: Query intent to evaluate inside this region's matched evidence.

Returns:
    A revalidated query carrying this parent-region declaration.

[Source: python/yosoi/locators.py:493](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/locators.py#L493-L502)

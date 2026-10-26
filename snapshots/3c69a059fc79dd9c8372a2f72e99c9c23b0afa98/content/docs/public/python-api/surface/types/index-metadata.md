---
title: "IndexMetadata"
description: "yosoi.surface.IndexMetadata Python API reference."
order: 0
---

`yosoi.surface.IndexMetadata`

```python
class IndexMetadata(ImmutableModel):
```

Preparation summary, not a current live-source status.

[Source: python/yosoi/surface.py:209](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L209-L217)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
identity: StrictStr = Field(description='Immutable interpretation identity.')
representation: StrictStr = Field(description='Document interpretation profile.')
source_bytes: int = Field(description='Retained source byte count.')
node_count: int = Field(description='Indexed evidence node count.')
coverage: Coverage = Field(description='Preparation completeness.')
root: NativeReference = Field(description='Full structural scope.')
```

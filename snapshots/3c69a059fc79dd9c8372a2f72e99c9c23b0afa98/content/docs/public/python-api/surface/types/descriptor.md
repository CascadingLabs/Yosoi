---
title: "Descriptor"
description: "yosoi.surface.Descriptor Python API reference."
order: 0
---

`yosoi.surface.Descriptor`

```python
class Descriptor(ImmutableModel):
```

Continuing source representation and the operations it actually supports.

[Source: python/yosoi/surface.py:235](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L235-L242)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: SurfaceId = Field(description='Surface identity.')
source: SourceId = Field(description='Source identity, without authority.')
representation: StrictStr = Field(description='Interpretation profile.')
controllable: StrictBool = Field(description='Whether this adapter offers control.')
capabilities: tuple[Capability, ...] = Field(description='Supported operations.')
```

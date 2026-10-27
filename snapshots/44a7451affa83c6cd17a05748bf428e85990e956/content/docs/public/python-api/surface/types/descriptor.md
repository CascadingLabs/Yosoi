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

[Source: python/yosoi/surface.py:242](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L242-L249)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: SurfaceId = Field(description='Surface identity.')
source: SourceId = Field(description='Source identity, without authority.')
representation: StrictStr = Field(description='Interpretation profile.')
controllable: StrictBool = Field(description='Whether this adapter offers control.')
capabilities: tuple[Capability, ...] = Field(description='Supported operations.')
```

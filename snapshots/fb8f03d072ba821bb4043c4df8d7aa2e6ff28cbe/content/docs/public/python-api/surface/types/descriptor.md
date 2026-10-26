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

[Source: python/yosoi/surface.py:242](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L242-L249)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: SurfaceId = Field(description='Surface identity.')
source: SourceId = Field(description='Source identity, without authority.')
representation: StrictStr = Field(description='Interpretation profile.')
controllable: StrictBool = Field(description='Whether this adapter offers control.')
capabilities: tuple[Capability, ...] = Field(description='Supported operations.')
```

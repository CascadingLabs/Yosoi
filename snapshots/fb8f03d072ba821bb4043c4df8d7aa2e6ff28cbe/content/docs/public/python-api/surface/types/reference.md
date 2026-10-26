---
title: "Reference"
description: "yosoi.surface.Reference Python API reference."
order: 0
---

`yosoi.surface.Reference`

```python
class Reference(ImmutableModel):
```

Representation-neutral evidence address, scoped to one observation.

[Source: python/yosoi/surface.py:137](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L137-L143)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
observation: ObservationId = Field(description='Immutable interpretation identity.')
address: AddressToken = Field(description='Opaque producer address; do not parse it.')
```

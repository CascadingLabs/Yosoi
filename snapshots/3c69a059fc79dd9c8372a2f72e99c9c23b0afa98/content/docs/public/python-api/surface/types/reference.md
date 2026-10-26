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

[Source: python/yosoi/surface.py:130](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L130-L136)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
observation: ObservationId = Field(description='Immutable interpretation identity.')
address: AddressToken = Field(description='Opaque producer address; do not parse it.')
```

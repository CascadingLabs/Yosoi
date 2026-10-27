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

[Source: python/yosoi/surface.py:137](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L137-L143)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
observation: ObservationId = Field(description='Immutable interpretation identity.')
address: AddressToken = Field(description='Opaque producer address; do not parse it.')
```

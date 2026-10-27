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

[Source: python/yosoi/surface.py:137](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L137-L143)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
observation: ObservationId = Field(description='Immutable interpretation identity.')
address: AddressToken = Field(description='Opaque producer address; do not parse it.')
```

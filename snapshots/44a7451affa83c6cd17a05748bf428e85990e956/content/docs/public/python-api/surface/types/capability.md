---
title: "Capability"
description: "yosoi.surface.Capability Python API reference."
order: 0
---

`yosoi.surface.Capability`

```python
class Capability(ImmutableModel):
```

Advertised operation with explicit read or control access.

[Source: python/yosoi/surface.py:231](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L231-L239)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: StrictStr = Field(description='Representation-owned capability name.')
access: Access = Field(description='Whether the source may change.')
control_domain: StrictStr | None = Field(default=None, description='Control arbitration domain.')
input_schema: StrictStr = Field(description='Versioned input schema identity.')
```

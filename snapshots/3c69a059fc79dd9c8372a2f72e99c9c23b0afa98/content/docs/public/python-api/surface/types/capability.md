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

[Source: python/yosoi/surface.py:224](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L224-L232)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: StrictStr = Field(description='Representation-owned capability name.')
access: Access = Field(description='Whether the source may change.')
control_domain: StrictStr | None = Field(default=None, description='Control arbitration domain.')
input_schema: StrictStr = Field(description='Versioned input schema identity.')
```

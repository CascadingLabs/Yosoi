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

[Source: python/yosoi/surface.py:231](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L231-L239)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
id: StrictStr = Field(description='Representation-owned capability name.')
access: Access = Field(description='Whether the source may change.')
control_domain: StrictStr | None = Field(default=None, description='Control arbitration domain.')
input_schema: StrictStr = Field(description='Versioned input schema identity.')
```

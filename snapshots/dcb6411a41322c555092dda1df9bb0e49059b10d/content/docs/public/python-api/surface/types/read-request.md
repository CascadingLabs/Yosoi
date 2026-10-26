---
title: "ReadRequest"
description: "yosoi.surface.ReadRequest Python API reference."
order: 0
---

`yosoi.surface.ReadRequest`

```python
class ReadRequest(ImmutableModel):
```

One shared request passed unchanged to either Rust-backed reader.

[Source: python/yosoi/surface.py:300](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L300-L309)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
operation: ReadOperation = Field(description='Navigation operation.')
budget: Budget = Field(default_factory=Budget, description='Complete Rust result bound.')
continuation: ContinuationToken | None = Field(default=None, description='Opaque shared continuation.')
```

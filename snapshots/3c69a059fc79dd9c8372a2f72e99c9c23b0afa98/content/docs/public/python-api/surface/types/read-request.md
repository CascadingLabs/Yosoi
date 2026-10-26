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

[Source: python/yosoi/surface.py:293](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L293-L302)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
operation: ReadOperation = Field(description='Navigation operation.')
budget: Budget = Field(default_factory=Budget, description='Complete Rust result bound.')
continuation: ContinuationToken | None = Field(default=None, description='Opaque shared continuation.')
```

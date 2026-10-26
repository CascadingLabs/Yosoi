---
title: "Entry"
description: "yosoi.surface.Entry Python API reference."
order: 0
---

`yosoi.surface.Entry`

```python
class Entry(ImmutableModel):
```

Representation-neutral hint for choosing the next region to inspect.

[Source: python/yosoi/surface.py:305](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L305-L312)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
reference: Reference = Field(description='Exact evidence address.')
kind: StrictStr = Field(description='Representation-specific category.')
label: StrictStr = Field(description='Short routing label.')
preview: StrictStr = Field(description='Bounded source-derived preview.')
members: int | None = Field(default=None, description='Known child count.')
```

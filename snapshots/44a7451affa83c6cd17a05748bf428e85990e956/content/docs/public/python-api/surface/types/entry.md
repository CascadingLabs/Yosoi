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

[Source: python/yosoi/surface.py:312](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L312-L319)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
reference: Reference = Field(description='Exact evidence address.')
kind: StrictStr = Field(description='Representation-specific category.')
label: StrictStr = Field(description='Short routing label.')
preview: StrictStr = Field(description='Bounded source-derived preview.')
members: int | None = Field(default=None, description='Known child count.')
```

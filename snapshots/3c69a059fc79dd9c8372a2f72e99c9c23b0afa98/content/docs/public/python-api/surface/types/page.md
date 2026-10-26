---
title: "Page"
description: "yosoi.surface.Page Python API reference."
order: 0
---

`yosoi.surface.Page`

```python
class Page(ImmutableModel):
```

Shared bounded region window; coverage and pagination are independent.

[Source: python/yosoi/surface.py:315](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L315-L325)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
observation: ObservationId = Field(description='Exact interpretation identity.')
total: int = Field(description='Eligible population before paging.')
offset: int = Field(description='Starting entry position.')
entries: tuple[Entry, ...] = Field(description='Returned routing entries.')
next: ContinuationToken | None = Field(default=None, description='Opaque next-window token.')
coverage: Coverage = Field(description='Completeness of source evidence.')
```

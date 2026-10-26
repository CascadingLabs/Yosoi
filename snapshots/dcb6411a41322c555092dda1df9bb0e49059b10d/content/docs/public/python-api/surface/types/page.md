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

[Source: python/yosoi/surface.py:322](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L322-L332)

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

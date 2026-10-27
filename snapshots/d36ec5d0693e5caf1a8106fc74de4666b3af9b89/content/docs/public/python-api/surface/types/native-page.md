---
title: "NativePage"
description: "yosoi.surface.NativePage Python API reference."
order: 0
---

`yosoi.surface.NativePage`

```python
class NativePage(ImmutableModel):
```

A bounded document-index window with explicit paging and coverage.

[Source: python/yosoi/surface.py:175](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L175-L187)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
capture: StrictStr = Field(description='Exact immutable interpretation.')
operation: StrictStr = Field(description='Operation that produced this page.')
total: int = Field(description='Eligible population before paging.')
offset: int = Field(description='Starting entry position.')
entries: tuple[NativeEntry, ...] = Field(description='Returned routing hints.')
omitted: int = Field(description='Population entries outside this response.')
next: Continuation | None = Field(default=None, description='Next window, if present.')
coverage: Coverage = Field(description='Source completeness independent of paging.')
```

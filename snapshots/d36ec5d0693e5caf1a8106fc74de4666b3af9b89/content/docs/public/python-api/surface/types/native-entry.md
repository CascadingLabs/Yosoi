---
title: "NativeEntry"
description: "yosoi.surface.NativeEntry Python API reference."
order: 0
---

`yosoi.surface.NativeEntry`

```python
class NativeEntry(ImmutableModel):
```

One structural routing hint backed by document evidence.

[Source: python/yosoi/surface.py:158](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L158-L172)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
reference: NativeReference = Field(description='Exact indexed evidence.')
kind: StrictStr = Field(description='Representation-specific category.')
label: StrictStr = Field(description='Short source-derived routing label.')
preview: StrictStr = Field(description='Bounded source preview.')
members: int | None = Field(default=None, description='Known child count.')
exemplar: NativeReference | None = Field(default=None, description='Repeated-group example.')
shape: StrictStr | None = Field(default=None, description='Advisory structural shape.')
view: StrictStr | None = Field(default=None, description='Named constituent view.')
```

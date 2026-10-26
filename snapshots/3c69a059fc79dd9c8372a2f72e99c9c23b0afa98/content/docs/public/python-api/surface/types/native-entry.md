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

[Source: python/yosoi/surface.py:151](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L151-L165)

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

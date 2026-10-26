---
title: "SourceReference"
description: "yosoi.surface.SourceReference Python API reference."
order: 0
---

`yosoi.surface.SourceReference`

```python
class SourceReference(ImmutableModel):
```

Binding from a combined index to one original independently captured view.

[Source: python/yosoi/surface.py:202](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L202-L206)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
view: StrictStr = Field(description='Constituent view name.')
reference: NativeReference = Field(description="Original view's exact reference.")
```

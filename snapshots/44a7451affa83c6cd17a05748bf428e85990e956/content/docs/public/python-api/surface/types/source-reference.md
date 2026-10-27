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

[Source: python/yosoi/surface.py:209](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L209-L213)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
view: StrictStr = Field(description='Constituent view name.')
reference: NativeReference = Field(description="Original view's exact reference.")
```

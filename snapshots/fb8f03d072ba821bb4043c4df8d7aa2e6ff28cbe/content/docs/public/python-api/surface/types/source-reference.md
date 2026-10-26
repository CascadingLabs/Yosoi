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

[Source: python/yosoi/surface.py:209](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L209-L213)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
view: StrictStr = Field(description='Constituent view name.')
reference: NativeReference = Field(description="Original view's exact reference.")
```

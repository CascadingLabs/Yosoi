---
title: "FrameArchiveRef"
description: "yosoi.surface.FrameArchiveRef Python API reference."
order: 0
---

`yosoi.surface.FrameArchiveRef`

```python
class FrameArchiveRef(ImmutableModel):
```

Normal Archive Document retaining actual PNG bytes and FrameInfo.

[Source: python/yosoi/surface.py:741](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L741-L744)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document: _ArchiveDocument = Field(description='Immutable stored PNG envelope.')
```

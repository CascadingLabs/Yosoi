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

[Source: python/yosoi/surface.py:741](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L741-L744)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document: _ArchiveDocument = Field(description='Immutable stored PNG envelope.')
```

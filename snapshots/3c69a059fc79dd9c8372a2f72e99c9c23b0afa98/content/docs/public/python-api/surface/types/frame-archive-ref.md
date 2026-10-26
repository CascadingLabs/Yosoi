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

[Source: python/yosoi/surface.py:734](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L734-L737)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document: _ArchiveDocument = Field(description='Immutable stored PNG envelope.')
```

---
title: "VideoArchiveRef"
description: "yosoi.surface.VideoArchiveRef Python API reference."
order: 0
---

`yosoi.surface.VideoArchiveRef`

```python
class VideoArchiveRef(ImmutableModel):
```

Normal Archive Document retaining source bytes and interpretation profile.

[Source: python/yosoi/surface.py:725](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L725-L731)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document: _ArchiveDocument = Field(description='Immutable stored document.')
observation: ObservationId = Field(description='Required interpretation identity on restore.')
```

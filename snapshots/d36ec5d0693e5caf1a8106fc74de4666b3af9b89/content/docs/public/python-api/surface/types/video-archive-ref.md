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

[Source: python/yosoi/surface.py:732](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L732-L738)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document: _ArchiveDocument = Field(description='Immutable stored document.')
observation: ObservationId = Field(description='Required interpretation identity on restore.')
```

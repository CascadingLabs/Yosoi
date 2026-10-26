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

[Source: python/yosoi/surface.py:732](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L732-L738)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
document: _ArchiveDocument = Field(description='Immutable stored document.')
observation: ObservationId = Field(description='Required interpretation identity on restore.')
```

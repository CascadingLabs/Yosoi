---
title: "VideoSession"
description: "yosoi.surface.VideoSession Python API reference."
order: 0
---

`yosoi.surface.VideoSession`

```python
class VideoSession(SurfaceConnection):
```

Read-only stateful exploration around a frozen VideoSurface.

[Source: python/yosoi/surface.py:1174](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L1174-L1187)

## Base classes

[SurfaceConnection](/yosoi/python-api/surface/types/surface-connection/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### open

```python
@classmethod
async def open(cls, path: str | Path, policy: SurfacePolicy | None=None, max_side: int=1920) -> Self:
```

Freeze local video and open a detached reader with bounded frame pixels.

[Source: python/yosoi/surface.py:1178](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L1178-L1187)

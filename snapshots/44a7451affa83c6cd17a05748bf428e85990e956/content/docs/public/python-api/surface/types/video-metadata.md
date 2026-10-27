---
title: "VideoMetadata"
description: "yosoi.surface.VideoMetadata Python API reference."
order: 0
---

`yosoi.surface.VideoMetadata`

```python
class VideoMetadata(ImmutableModel):
```

Primary video stream metadata captured from the frozen source.

[Source: python/yosoi/surface.py:679](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L679-L698)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
name: StrictStr = Field(description='Original display name, never a reopening address.')
source_sha256: StrictStr = Field(description='Digest of complete frozen bytes.')
source_bytes: int = Field(description='Original source length.')
container: StrictStr = Field(description='Demuxer container names.')
codec: StrictStr = Field(description='Primary stream codec.')
width: int = Field(description='Original raster width.')
height: int = Field(description='Original raster height.')
duration_us: int = Field(description='Primary duration in microseconds.')
duration_estimated: StrictBool = Field(description='Whether container duration was used.')
stream_start_us: int = Field(description='Primary source start timestamp.')
time_base: StrictStr = Field(description='Demuxer time-base expression.')
audio_streams: int = Field(description='Audio stream count; audio is not decoded.')
decoder: StrictStr = Field(description='Decoder version defining interpretation.')
```

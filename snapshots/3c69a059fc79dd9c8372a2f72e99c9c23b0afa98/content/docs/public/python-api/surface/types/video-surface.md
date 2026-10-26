---
title: "VideoSurface"
description: "yosoi.surface.VideoSurface Python API reference."
order: 0
---

`yosoi.surface.VideoSurface`

```python
class VideoSurface:
```

Frozen local video with a lazy timeline and read-only frame capabilities.

Open with await VideoSurface.open(path). No OCR, audio transcription, playback,
live-stream subscription or control is provided. Cancelling the Python await
leaves Rust finishing bounded cleanup in the background. Snapshot resources
are released when the owning handle is dropped.

[Source: python/yosoi/surface.py:774](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L774-L858)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, handle: _native.VideoSurface) -> None:
```

Wrap a Rust-owned snapshot returned by open or read_from.

[Source: python/yosoi/surface.py:783](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L783-L785)

### open

```python
@classmethod
async def open(cls, path: str | Path, policy: VideoPolicy | None=None) -> Self:
```

Snapshot and probe a regular local file; failures raise VideoError.

Requires FFmpeg and FFprobe on PATH or YOSOI_FFMPEG/YOSOI_FFPROBE.
The original file can be removed once this returns successfully.

[Source: python/yosoi/surface.py:788](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L788-L799)

### descriptor

```python
@property
def descriptor(self) -> Descriptor:
```

Return read/frame capabilities with controllable false.

[Source: python/yosoi/surface.py:802](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L802-L804)

### observation

```python
@property
def observation(self) -> Observation:
```

Return frozen source and decoder-profile interpretation identity.

[Source: python/yosoi/surface.py:807](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L807-L809)

### root_reference

```python
@property
def root_reference(self) -> Reference:
```

Return the complete visual timeline scope.

[Source: python/yosoi/surface.py:812](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L812-L814)

### metadata

```python
@property
def metadata(self) -> VideoMetadata:
```

Return original video dimensions and primary stream timing.

[Source: python/yosoi/surface.py:817](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L817-L819)

### policy

```python
@property
def policy(self) -> VideoPolicy:
```

Return the processing bounds retained by this observation.

[Source: python/yosoi/surface.py:822](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L822-L824)

### read

```python
def read(self, request: ReadRequest) -> ReadResult:
```

Read timeline evidence; search and parent are unsupported.

[Source: python/yosoi/surface.py:826](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L826-L828)

### at

```python
def at(self, position_us: int) -> Reference:
```

Address stream-relative time for decoding the first frame at or after it.

[Source: python/yosoi/surface.py:830](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L830-L832)

### frame

```python
async def frame(self, reference: Reference) -> DecodedFrame:
```

Decode one frame; the final-frame tail may have no frame at or after it.

[Source: python/yosoi/surface.py:834](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L834-L836)

### crop

```python
async def crop(self, reference: Reference, rect: PixelRect) -> DecodedFrame:
```

Decode/crop a full-frame reference in decoded-canvas coordinates.

[Source: python/yosoi/surface.py:838](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L838-L842)

### write_to

```python
async def write_to(self, archive: Archive) -> VideoArchiveRef:
```

Archive the frozen source and interpretation without live authority.

[Source: python/yosoi/surface.py:844](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L844-L848)

### read_from

```python
@classmethod
async def read_from(cls, archive: Archive, reference: VideoArchiveRef) -> Self:
```

Restore a timeline without probing; new frame decoding still needs FFmpeg.

[Source: python/yosoi/surface.py:851](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L851-L858)

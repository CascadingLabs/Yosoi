---
title: "DecodedFrame"
description: "yosoi.surface.DecodedFrame Python API reference."
order: 0
---

`yosoi.surface.DecodedFrame`

```python
class DecodedFrame:
```

Immutable Rust-owned PNG evidence, restored without a decoder when archived.

[Source: python/yosoi/surface.py:747](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L747-L778)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, handle: _native.DecodedFrame) -> None:
```

Wrap a native artifact returned by frame, crop or read_from.

[Source: python/yosoi/surface.py:750](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L750-L752)

### info

```python
@property
def info(self) -> FrameInfo:
```

Return measured time, pixel coordinates and PNG integrity metadata.

[Source: python/yosoi/surface.py:755](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L755-L757)

### png

```python
@property
def png(self) -> bytes:
```

Copy encoded PNG bytes; binary size is separate from text read budgets.

[Source: python/yosoi/surface.py:760](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L760-L762)

### write_to

```python
async def write_to(self, archive: Archive) -> FrameArchiveRef:
```

Store verified PNG evidence using the existing Rust Archive backend.

[Source: python/yosoi/surface.py:764](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L764-L768)

### read_from

```python
@classmethod
async def read_from(cls, archive: Archive, reference: FrameArchiveRef) -> Self:
```

Verify and restore saved PNG pixels without FFmpeg or the original file.

[Source: python/yosoi/surface.py:771](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L771-L778)

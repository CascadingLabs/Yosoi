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

[Source: python/yosoi/surface.py:740](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L740-L771)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, handle: _native.DecodedFrame) -> None:
```

Wrap a native artifact returned by frame, crop or read_from.

[Source: python/yosoi/surface.py:743](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L743-L745)

### info

```python
@property
def info(self) -> FrameInfo:
```

Return measured time, pixel coordinates and PNG integrity metadata.

[Source: python/yosoi/surface.py:748](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L748-L750)

### png

```python
@property
def png(self) -> bytes:
```

Copy encoded PNG bytes; binary size is separate from text read budgets.

[Source: python/yosoi/surface.py:753](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L753-L755)

### write_to

```python
async def write_to(self, archive: Archive) -> FrameArchiveRef:
```

Store verified PNG evidence using the existing Rust Archive backend.

[Source: python/yosoi/surface.py:757](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L757-L761)

### read_from

```python
@classmethod
async def read_from(cls, archive: Archive, reference: FrameArchiveRef) -> Self:
```

Verify and restore saved PNG pixels without FFmpeg or the original file.

[Source: python/yosoi/surface.py:764](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L764-L771)

---
title: "FrameInfo"
description: "yosoi.surface.FrameInfo Python API reference."
order: 0
---

`yosoi.surface.FrameInfo`

```python
class FrameInfo(ImmutableModel):
```

Actual PNG provenance, separating requested time from measured source PTS.

[Source: python/yosoi/surface.py:701](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L701-L718)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
reference: Reference = Field(description='Exact video evidence address.')
requested_us: int = Field(description='Requested stream-relative microseconds.')
source_pts_us: int = Field(description='Measured source frame timestamp.')
position_us: int | None = Field(description='Measured stream-relative position, absent for pre-roll.')
canvas_width: int = Field(description='Full decoded-frame width.')
canvas_height: int = Field(description='Full decoded-frame height.')
width: int = Field(description='Returned PNG width.')
height: int = Field(description='Returned PNG height.')
region: PixelRect | None = Field(description='Crop in full decoded-frame coordinates.')
png_sha256: StrictStr = Field(description='Digest of returned PNG bytes.')
png_bytes: int = Field(description='Encoded PNG byte count.')
```

---
title: "VideoPolicy"
description: "yosoi.surface.VideoPolicy Python API reference."
order: 0
---

`yosoi.surface.VideoPolicy`

```python
class VideoPolicy(ImmutableModel):
```

Snapshot and decoder limits. Rust validates the supported combinations.

[Source: python/yosoi/surface.py:650](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L650-L676)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
max_source_bytes: int = Field(default=33554432, strict=True, ge=0, description='Source byte cap.')
frame_max_side: int = Field(default=1920, strict=True, ge=0, description='Decoded side cap; never upscales.')
max_frame_bytes: int = Field(default=8388608, strict=True, ge=0, description='PNG byte cap per artifact.')
min_interval_us: int = Field(default=250000, strict=True, ge=0, description='Smallest automatic timeline interval.')
max_duration_us: int = Field(default=21600000000, strict=True, ge=0, description='Primary duration cap.')
tool_timeout_ms: int = Field(default=30000, strict=True, ge=0, description='Per-tool timeout in milliseconds.')
```

---
title: "BrowserSurface"
description: "yosoi.surface.BrowserSurface Python API reference."
order: 0
---

`yosoi.surface.BrowserSurface`

```python
class BrowserSurface(SurfaceConnection):
```

An isolated live browser with source-specific actions and archive support.

[Source: python/yosoi/surface.py:1158](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L1158-L1171)

## Base classes

[SurfaceConnection](/yosoi/python-api/surface/types/surface-connection/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### open

```python
@classmethod
async def open(cls, url: str, policy: SurfacePolicy | None=None, headless: bool=True) -> Self:
```

Open a supported regular browser, initially detached from live authority.

[Source: python/yosoi/surface.py:1162](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L1162-L1171)

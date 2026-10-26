---
title: "SurfaceConnection"
description: "yosoi.surface.SurfaceConnection Python API reference."
order: 0
---

`yosoi.surface.SurfaceConnection`

```python
class SurfaceConnection:
```

Shared lifecycle for a source-specific browser or video connection.

Use a source's open factory, then await close or use async with. Cancellation
stops waiting; it does not prove that a dispatched effect was undone.

[Source: python/yosoi/surface.py:1112](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L1112-L1155)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, handle: _native.BrowserSurface | _native.VideoSession) -> None:
```

Wrap a native source connection; prefer its asynchronous factory.

[Source: python/yosoi/surface.py:1119](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L1119-L1121)

### __aenter__

```python
async def __aenter__(self) -> Self:
```

Keep source resources alive until context cleanup.

[Source: python/yosoi/surface.py:1123](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L1123-L1125)

### __aexit__

```python
async def __aexit__(self, *_: object) -> None:
```

Await source cleanup even when the context body raises.

[Source: python/yosoi/surface.py:1127](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L1127-L1129)

### ready

```python
async def ready(self) -> dict[str, object]:
```

Return capabilities and bounded initial evidence without granting control.

[Source: python/yosoi/surface.py:1131](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L1131-L1133)

### execute

```python
async def execute(self, command: Mapping[str, object]) -> dict[str, object]:
```

Execute one bounded Surface command through the source implementation.

Use serialized references from current evidence. Browser effects require
live attachment, hot ownership and eligibility. An error can follow a
dispatched effect; inspect retained evidence before retrying.

[Source: python/yosoi/surface.py:1135](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L1135-L1142)

### outcome

```python
async def outcome(self) -> Outcome | None:
```

Snapshot retained evidence, including partial attempts, when enabled.

[Source: python/yosoi/surface.py:1144](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L1144-L1147)

### close

```python
async def close(self) -> Outcome | None:
```

Await source cleanup and final retention; repeated calls are harmless.

Retained certainty and gaps remain available through outcome on failure.

[Source: python/yosoi/surface.py:1149](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L1149-L1155)

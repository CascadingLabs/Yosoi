---
title: "SurfaceRead"
description: "yosoi.surface.SurfaceRead Python API reference."
order: 0
---

`yosoi.surface.SurfaceRead`

```python
class SurfaceRead(Protocol):
```

Common pure reading contract; frame decoding and effects are capabilities.

[Source: python/yosoi/surface.py:377](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L377-L397)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### descriptor

```python
@property
def descriptor(self) -> Descriptor:
```

Return supported operations and source identity.

[Source: python/yosoi/surface.py:381](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L381-L383)

### observation

```python
@property
def observation(self) -> Observation:
```

Return immutable interpretation metadata.

[Source: python/yosoi/surface.py:386](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L386-L388)

### root_reference

```python
@property
def root_reference(self) -> Reference:
```

Return the full scope of this representation.

[Source: python/yosoi/surface.py:391](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L391-L393)

### read

```python
def read(self, request: ReadRequest) -> ReadResult:
```

Read bounded evidence; unsupported or foreign requests raise SurfaceError.

[Source: python/yosoi/surface.py:395](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L395-L397)

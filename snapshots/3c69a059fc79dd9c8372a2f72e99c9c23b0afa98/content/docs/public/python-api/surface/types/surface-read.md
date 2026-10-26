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

[Source: python/yosoi/surface.py:370](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L370-L390)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### descriptor

```python
@property
def descriptor(self) -> Descriptor:
```

Return supported operations and source identity.

[Source: python/yosoi/surface.py:374](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L374-L376)

### observation

```python
@property
def observation(self) -> Observation:
```

Return immutable interpretation metadata.

[Source: python/yosoi/surface.py:379](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L379-L381)

### root_reference

```python
@property
def root_reference(self) -> Reference:
```

Return the full scope of this representation.

[Source: python/yosoi/surface.py:384](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L384-L386)

### read

```python
def read(self, request: ReadRequest) -> ReadResult:
```

Read bounded evidence; unsupported or foreign requests raise SurfaceError.

[Source: python/yosoi/surface.py:388](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L388-L390)

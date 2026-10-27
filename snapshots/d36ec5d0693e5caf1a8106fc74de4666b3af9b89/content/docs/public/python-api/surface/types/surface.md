---
title: "Surface"
description: "yosoi.surface.Surface Python API reference."
order: 0
---

`yosoi.surface.Surface`

```python
class Surface:
```

Reusable immutable index of any supported Document class.

Args:
    document: Retained source bytes and interpretation profile.
    limits: Preparation bounds, independent of a task or language model.

Raises:
    SurfaceError: Input interpretation or resource limits fail.

[Source: python/yosoi/surface.py:400](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L400-L582)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, document: Document, limits: Limits | None=None) -> None:
```

Prepare document evidence in Rust without network or model calls.

[Source: python/yosoi/surface.py:411](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L411-L415)

### metadata

```python
@property
def metadata(self) -> IndexMetadata:
```

Return source size, index size, root and preparation coverage.

[Source: python/yosoi/surface.py:424](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L424-L426)

### identity

```python
@property
def identity(self) -> str:
```

Return the immutable document interpretation identity.

[Source: python/yosoi/surface.py:429](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L429-L431)

### representation

```python
@property
def representation(self) -> str:
```

Return the indexed document's interpretation profile.

[Source: python/yosoi/surface.py:434](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L434-L436)

### source_bytes

```python
@property
def source_bytes(self) -> int:
```

Return retained source size, separate from response budgets.

[Source: python/yosoi/surface.py:439](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L439-L441)

### node_count

```python
@property
def node_count(self) -> int:
```

Return indexed evidence count, including reduced routing regions.

[Source: python/yosoi/surface.py:444](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L444-L446)

### coverage

```python
@property
def coverage(self) -> Coverage:
```

Return preparation coverage, independently of response pagination.

[Source: python/yosoi/surface.py:449](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L449-L451)

### root

```python
@property
def root(self) -> NativeReference:
```

Return the exact reference covering the complete indexed document.

[Source: python/yosoi/surface.py:454](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L454-L456)

### overview

```python
def overview(self, *, continuation: Continuation | None=None, budget: Budget | None=None) -> NativePage:
```

Read a reduced overview; omitted evidence remains reachable by paging.

[Source: python/yosoi/surface.py:474](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L474-L480)

### find

```python
def find(self, query: str, *, continuation: Continuation | None=None, budget: Budget | None=None) -> NativePage:
```

Find literal source text and attributes; Rust rejects empty queries.

[Source: python/yosoi/surface.py:482](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L482-L492)

### expand

```python
def expand(self, reference: NativeReference, *, continuation: Continuation | None=None, budget: Budget | None=None) -> NativePage:
```

Read one region's members; foreign references raise SurfaceError.

[Source: python/yosoi/surface.py:494](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L494-L504)

### inspect

```python
def inspect(self, reference: NativeReference, *, continuation: Continuation | None=None, budget: Budget | None=None) -> NativeInspection:
```

Read source detail in UTF-8 chunks bound to the original reference.

[Source: python/yosoi/surface.py:506](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L506-L516)

### parent

```python
def parent(self, reference: NativeReference) -> NativeReference | None:
```

Return the structural parent, or None at the root.

[Source: python/yosoi/surface.py:518](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L518-L522)

### coordinate

```python
def coordinate(self, reference: NativeReference) -> Coordinate:
```

Return representation-specific source coordinates without live resolution.

[Source: python/yosoi/surface.py:524](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L524-L526)

### validate

```python
def validate(self, reference: NativeReference) -> None:
```

Reject references outside this exact immutable interpretation.

[Source: python/yosoi/surface.py:528](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L528-L530)

### source_reference

```python
def source_reference(self, reference: NativeReference) -> SourceReference | None:
```

Resolve a combined-view reference to its original captured view.

[Source: python/yosoi/surface.py:532](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L532-L536)

### combine

```python
@classmethod
def combine(cls, scope: str, views: Mapping[str, Surface], limits: Limits | None=None) -> Self:
```

Combine named captures without claiming an atomic observation.

[Source: python/yosoi/surface.py:539](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L539-L549)

### view

```python
def view(self, name: str) -> Surface | None:
```

Return an original constituent view, or None if the name is absent.

[Source: python/yosoi/surface.py:551](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L551-L554)

### project

```python
def project(self, name: str, reference: NativeReference) -> NativeReference:
```

Project an original view reference into this combined index.

[Source: python/yosoi/surface.py:556](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L556-L560)

### from_image

```python
@classmethod
def from_image(cls, content: bytes, tile_side: int=256, limits: Limits | None=None) -> Self:
```

Index PNG/JPEG pixels as bounded regions without OCR or EXIF rotation.

[Source: python/yosoi/surface.py:563](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L563-L573)

### crop

```python
def crop(self, reference: NativeReference, max_png_bytes: int=8388608) -> ImageCrop:
```

Materialize an indexed image region; binary and text budgets are separate.

[Source: python/yosoi/surface.py:575](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L575-L582)

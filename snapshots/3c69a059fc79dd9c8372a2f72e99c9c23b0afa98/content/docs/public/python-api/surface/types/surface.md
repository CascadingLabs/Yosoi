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

[Source: python/yosoi/surface.py:393](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L393-L575)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### __init__

```python
def __init__(self, document: Document, limits: Limits | None=None) -> None:
```

Prepare document evidence in Rust without network or model calls.

[Source: python/yosoi/surface.py:404](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L404-L408)

### metadata

```python
@property
def metadata(self) -> IndexMetadata:
```

Return source size, index size, root and preparation coverage.

[Source: python/yosoi/surface.py:417](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L417-L419)

### identity

```python
@property
def identity(self) -> str:
```

Return the immutable document interpretation identity.

[Source: python/yosoi/surface.py:422](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L422-L424)

### representation

```python
@property
def representation(self) -> str:
```

Return the indexed document's interpretation profile.

[Source: python/yosoi/surface.py:427](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L427-L429)

### source_bytes

```python
@property
def source_bytes(self) -> int:
```

Return retained source size, separate from response budgets.

[Source: python/yosoi/surface.py:432](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L432-L434)

### node_count

```python
@property
def node_count(self) -> int:
```

Return indexed evidence count, including reduced routing regions.

[Source: python/yosoi/surface.py:437](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L437-L439)

### coverage

```python
@property
def coverage(self) -> Coverage:
```

Return preparation coverage, independently of response pagination.

[Source: python/yosoi/surface.py:442](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L442-L444)

### root

```python
@property
def root(self) -> NativeReference:
```

Return the exact reference covering the complete indexed document.

[Source: python/yosoi/surface.py:447](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L447-L449)

### overview

```python
def overview(self, *, continuation: Continuation | None=None, budget: Budget | None=None) -> NativePage:
```

Read a reduced overview; omitted evidence remains reachable by paging.

[Source: python/yosoi/surface.py:467](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L467-L473)

### find

```python
def find(self, query: str, *, continuation: Continuation | None=None, budget: Budget | None=None) -> NativePage:
```

Find literal source text and attributes; Rust rejects empty queries.

[Source: python/yosoi/surface.py:475](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L475-L485)

### expand

```python
def expand(self, reference: NativeReference, *, continuation: Continuation | None=None, budget: Budget | None=None) -> NativePage:
```

Read one region's members; foreign references raise SurfaceError.

[Source: python/yosoi/surface.py:487](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L487-L497)

### inspect

```python
def inspect(self, reference: NativeReference, *, continuation: Continuation | None=None, budget: Budget | None=None) -> NativeInspection:
```

Read source detail in UTF-8 chunks bound to the original reference.

[Source: python/yosoi/surface.py:499](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L499-L509)

### parent

```python
def parent(self, reference: NativeReference) -> NativeReference | None:
```

Return the structural parent, or None at the root.

[Source: python/yosoi/surface.py:511](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L511-L515)

### coordinate

```python
def coordinate(self, reference: NativeReference) -> Coordinate:
```

Return representation-specific source coordinates without live resolution.

[Source: python/yosoi/surface.py:517](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L517-L519)

### validate

```python
def validate(self, reference: NativeReference) -> None:
```

Reject references outside this exact immutable interpretation.

[Source: python/yosoi/surface.py:521](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L521-L523)

### source_reference

```python
def source_reference(self, reference: NativeReference) -> SourceReference | None:
```

Resolve a combined-view reference to its original captured view.

[Source: python/yosoi/surface.py:525](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L525-L529)

### combine

```python
@classmethod
def combine(cls, scope: str, views: Mapping[str, Surface], limits: Limits | None=None) -> Self:
```

Combine named captures without claiming an atomic observation.

[Source: python/yosoi/surface.py:532](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L532-L542)

### view

```python
def view(self, name: str) -> Surface | None:
```

Return an original constituent view, or None if the name is absent.

[Source: python/yosoi/surface.py:544](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L544-L547)

### project

```python
def project(self, name: str, reference: NativeReference) -> NativeReference:
```

Project an original view reference into this combined index.

[Source: python/yosoi/surface.py:549](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L549-L553)

### from_image

```python
@classmethod
def from_image(cls, content: bytes, tile_side: int=256, limits: Limits | None=None) -> Self:
```

Index PNG/JPEG pixels as bounded regions without OCR or EXIF rotation.

[Source: python/yosoi/surface.py:556](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L556-L566)

### crop

```python
def crop(self, reference: NativeReference, max_png_bytes: int=8388608) -> ImageCrop:
```

Materialize an indexed image region; binary and text budgets are separate.

[Source: python/yosoi/surface.py:568](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L568-L575)

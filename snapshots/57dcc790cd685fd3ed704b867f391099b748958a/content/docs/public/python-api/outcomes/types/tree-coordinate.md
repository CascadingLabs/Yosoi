---
title: "TreeCoordinate"
description: "yosoi.outcomes.TreeCoordinate Python API reference."
order: 0
---

`yosoi.outcomes.TreeCoordinate`

```python
class TreeCoordinate(ImmutableModel):
```

Source-tree location with optional byte and expanded-name evidence.

Attributes:
    child_path: Nonempty sequence of positive, one-based child indices.
    source_bytes: Exact source-payload byte range, when available.
    expanded_name_path: Nonempty XML expanded-name path, when supplied.
        Correspondence with child_path or bytes is not checked against document
        contents.

[Source: python/yosoi/outcomes.py:197](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/outcomes.py#L197-L275)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
child_path: tuple[PositiveU32, ...]
source_bytes: ByteRange | None = None
expanded_name_path: tuple[ExpandedNamePathSegment, ...] | None = Field(default=None, exclude_if=lambda value: value is None)
```

## Methods

### try_new

```python
@classmethod
def try_new(cls, child_path: tuple[int, ...], source_bytes: ByteRange | None=None) -> Self:
```

Validate a child path and retain optional exact-byte evidence.

Args:
    child_path: Nonempty sequence of positive one-based child indices.
    source_bytes: Exact source-byte range, when available.

Returns:
    A coordinate without verifying tree membership or payload bounds.

Raises:
    LocatorError: The child path or supplied wire data is invalid.

[Source: python/yosoi/outcomes.py:221](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/outcomes.py#L221-L243)

### with_expanded_name_path

```python
@classmethod
def with_expanded_name_path(cls, child_path: tuple[int, ...], source_bytes: ByteRange | None, expanded_name_path: tuple[ExpandedNamePathSegment, ...]) -> Self:
```

Retain child-path, byte, and XML expanded-name evidence.

Args:
    child_path: Nonempty sequence of positive one-based child indices.
    source_bytes: Exact source-byte range, when available.
    expanded_name_path: Nonempty sequence of validated expanded-name segments.

Returns:
    A coordinate without verifying correspondence between the paths and bytes.

Raises:
    LocatorError: A path is empty or its supplied structure is invalid.

[Source: python/yosoi/outcomes.py:246](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/outcomes.py#L246-L275)

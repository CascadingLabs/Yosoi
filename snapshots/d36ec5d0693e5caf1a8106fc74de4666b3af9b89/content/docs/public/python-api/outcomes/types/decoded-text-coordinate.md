---
title: "DecodedTextCoordinate"
description: "yosoi.outcomes.DecodedTextCoordinate Python API reference."
order: 0
---

`yosoi.outcomes.DecodedTextCoordinate`

```python
class DecodedTextCoordinate(ImmutableModel):
```

Paired source-byte and decoded-text scalar offsets for a match.

Attributes:
    byte_range: Exact retained-source byte range.
    scalar_range: Decoded-text Unicode-scalar range. Correspondence between ranges
        is supplied by the caller, not verified against text.

[Source: python/yosoi/outcomes.py:359](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/outcomes.py#L359-L402)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
byte_range: ByteRange
scalar_range: TextRange
```

## Methods

### new

```python
@classmethod
def new(cls, byte_range: ByteRange, scalar_range: TextRange) -> Self:
```

Pair source-byte and decoded-text scalar ranges.

Args:
    byte_range: Exact retained-source byte offsets.
    scalar_range: Decoded-text Unicode-scalar offsets for the same match.

Returns:
    A coordinate without verifying correspondence between the supplied ranges.

Raises:
    LocatorError: Supplied range data cannot form a valid Rust coordinate.

[Source: python/yosoi/outcomes.py:380](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/outcomes.py#L380-L402)

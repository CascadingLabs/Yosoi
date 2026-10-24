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

[Source: python/yosoi/outcomes.py:359](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/outcomes.py#L359-L402)

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

[Source: python/yosoi/outcomes.py:380](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/outcomes.py#L380-L402)

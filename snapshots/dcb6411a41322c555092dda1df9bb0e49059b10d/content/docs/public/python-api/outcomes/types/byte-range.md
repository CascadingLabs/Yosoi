---
title: "ByteRange"
description: "yosoi.outcomes.ByteRange Python API reference."
order: 0
---

`yosoi.outcomes.ByteRange`

```python
class ByteRange(ImmutableModel):
```

Half-open byte offsets in an owned source payload, allowing empty ranges.

Attributes:
    start: Inclusive starting byte offset.
    end: Exclusive ending byte offset, not less than start. Bounds and UTF-8
        boundaries are not verified against a document.

[Source: python/yosoi/outcomes.py:69](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/outcomes.py#L69-L104)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
start: U64
end: U64
```

## Methods

### try_new

```python
@classmethod
def try_new(cls, start: int, end: int) -> Self:
```

Validate half-open byte offsets through the Rust constructor.

Args:
    start: Inclusive source-byte offset.
    end: Exclusive offset; equality permits an empty range.

Returns:
    Validated offsets without a source-payload bounds or UTF-8 boundary check.

Raises:
    LocatorError: The range is reversed or its wire values are invalid.

[Source: python/yosoi/outcomes.py:88](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/outcomes.py#L88-L104)

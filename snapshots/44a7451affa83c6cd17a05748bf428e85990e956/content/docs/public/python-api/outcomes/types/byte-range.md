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

[Source: python/yosoi/outcomes.py:69](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/outcomes.py#L69-L104)

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

[Source: python/yosoi/outcomes.py:88](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/outcomes.py#L88-L104)

---
title: "TextRange"
description: "yosoi.outcomes.TextRange Python API reference."
order: 0
---

`yosoi.outcomes.TextRange`

```python
class TextRange(ImmutableModel):
```

Half-open Unicode-scalar offsets in decoded text, allowing empty ranges.

Attributes:
    start: Inclusive scalar offset, not a UTF-8 byte or grapheme index.
    end: Exclusive scalar offset, not less than start. Text bounds are not verified.

[Source: python/yosoi/outcomes.py:107](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/outcomes.py#L107-L141)

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

Validate half-open Unicode-scalar offsets through Rust.

Args:
    start: Inclusive decoded-text scalar offset.
    end: Exclusive scalar offset; equality permits an empty range.

Returns:
    Validated offsets without checking text bounds or grapheme boundaries.

Raises:
    LocatorError: The range is reversed or its wire values are invalid.

[Source: python/yosoi/outcomes.py:125](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/outcomes.py#L125-L141)

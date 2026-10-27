---
title: "AddressableByteLimit"
description: "yosoi.scalars.AddressableByteLimit Python API reference."
order: 0
---

`yosoi.scalars.AddressableByteLimit`

```python
class AddressableByteLimit(ValidatedInteger):
```

Positive u64 byte bound that also fits the Rust platform address size.

[Source: python/yosoi/scalars.py:262](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/scalars.py#L262-L277)

## Base classes

[ValidatedInteger](/yosoi/python-api/scalars/types/validated-integer/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### as_usize

```python
def as_usize(self) -> int:
```

Return the byte bound already checked to fit Rust platform address size.

[Source: python/yosoi/scalars.py:267](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/scalars.py#L267-L269)

### to_byte_limit

```python
def to_byte_limit(self) -> ByteLimit:
```

Convert to a positive byte limit; the value is measured in bytes.

[Source: python/yosoi/scalars.py:271](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/scalars.py#L271-L277)

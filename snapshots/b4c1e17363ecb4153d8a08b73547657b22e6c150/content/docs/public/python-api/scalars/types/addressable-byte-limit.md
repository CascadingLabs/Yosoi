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

[Source: python/yosoi/scalars.py:262](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/scalars.py#L262-L277)

## Base classes

[ValidatedInteger](/yosoi/python-api/scalars/types/validated-integer/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### as_usize

```python
def as_usize(self) -> int:
```

Return the byte bound already checked to fit Rust platform address size.

[Source: python/yosoi/scalars.py:267](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/scalars.py#L267-L269)

### to_byte_limit

```python
def to_byte_limit(self) -> ByteLimit:
```

Convert to a positive byte limit; the value is measured in bytes.

[Source: python/yosoi/scalars.py:271](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/scalars.py#L271-L277)

---
title: "CaptureDeadline"
description: "yosoi.scalars.CaptureDeadline Python API reference."
order: 0
---

`yosoi.scalars.CaptureDeadline`

```python
class CaptureDeadline(_RustUnsignedResult):
```

Positive capture deadline represented in microseconds.

[Source: python/yosoi/scalars.py:382](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/scalars.py#L382-L402)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### as_microseconds

```python
def as_microseconds(self) -> int:
```

Return the positive elapsed bound in microseconds, not a timestamp.

[Source: python/yosoi/scalars.py:385](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/scalars.py#L385-L387)

### duration

```python
def duration(self) -> CaptureDuration:
```

Convert the microsecond capture bound to a typed duration value.

Returns:
    A Rust-produced duration preserving the exact microsecond units.

Raises:
    ValueError: Native capture-duration conversion cannot represent the value.

[Source: python/yosoi/scalars.py:389](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/scalars.py#L389-L402)

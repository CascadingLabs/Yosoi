---
title: "MaximumElapsed"
description: "yosoi.scalars.MaximumElapsed Python API reference."
order: 0
---

`yosoi.scalars.MaximumElapsed`

```python
class MaximumElapsed(ValidatedInteger):
```

Positive u64 elapsed budget measured in microseconds, not a timestamp.

[Source: python/yosoi/scalars.py:323](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/scalars.py#L323-L343)

## Base classes

[ValidatedInteger](/yosoi/python-api/scalars/types/validated-integer/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### default

```python
@classmethod
def default(cls) -> Self:
```

Return the Rust default elapsed budget in microseconds.

[Source: python/yosoi/scalars.py:329](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/scalars.py#L329-L331)

### as_microseconds

```python
def as_microseconds(self) -> int:
```

Return the elapsed budget in microseconds without creating a deadline.

[Source: python/yosoi/scalars.py:333](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/scalars.py#L333-L335)

### to_capture_deadline

```python
def to_capture_deadline(self) -> CaptureDeadline:
```

Convert the positive elapsed limit to a microsecond deadline.

[Source: python/yosoi/scalars.py:337](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/scalars.py#L337-L343)

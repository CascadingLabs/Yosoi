---
title: "ResourceLimit"
description: "yosoi.scalars.ResourceLimit Python API reference."
order: 0
---

`yosoi.scalars.ResourceLimit`

```python
class ResourceLimit(ValidatedInteger):
```

Positive addressable u32 count of browser resources admitted to a capture.

[Source: python/yosoi/scalars.py:295](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/scalars.py#L295-L306)

## Base classes

[ValidatedInteger](/yosoi/python-api/scalars/types/validated-integer/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### to_nonzero

```python
def to_nonzero(self) -> NonZeroU32:
```

Return the corresponding positive 32-bit resource bound.

[Source: python/yosoi/scalars.py:300](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/scalars.py#L300-L306)

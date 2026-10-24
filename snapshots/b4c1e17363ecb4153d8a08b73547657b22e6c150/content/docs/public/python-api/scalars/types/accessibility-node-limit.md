---
title: "AccessibilityNodeLimit"
description: "yosoi.scalars.AccessibilityNodeLimit Python API reference."
order: 0
---

`yosoi.scalars.AccessibilityNodeLimit`

```python
class AccessibilityNodeLimit(ValidatedInteger):
```

Positive addressable u32 bound on accessibility snapshot nodes.

[Source: python/yosoi/scalars.py:309](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/scalars.py#L309-L320)

## Base classes

[ValidatedInteger](/yosoi/python-api/scalars/types/validated-integer/)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### to_nonzero

```python
def to_nonzero(self) -> NonZeroU32:
```

Return the corresponding positive 32-bit accessibility-node bound.

[Source: python/yosoi/scalars.py:314](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/scalars.py#L314-L320)

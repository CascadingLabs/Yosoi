---
title: "ByteLimit"
description: "yosoi.scalars.ByteLimit Python API reference."
order: 0
---

`yosoi.scalars.ByteLimit`

```python
class ByteLimit(_RustUnsignedResult):
```

Positive byte limit returned by a policy conversion; units are bytes.

[Source: python/yosoi/scalars.py:373](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/scalars.py#L373-L379)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### as_usize

```python
def as_usize(self) -> int:
```

Return converted bytes already checked for platform addressability.

[Source: python/yosoi/scalars.py:376](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/scalars.py#L376-L379)

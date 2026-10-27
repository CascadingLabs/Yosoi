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

[Source: python/yosoi/scalars.py:373](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/scalars.py#L373-L379)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Methods

### as_usize

```python
def as_usize(self) -> int:
```

Return converted bytes already checked for platform addressability.

[Source: python/yosoi/scalars.py:376](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/scalars.py#L376-L379)

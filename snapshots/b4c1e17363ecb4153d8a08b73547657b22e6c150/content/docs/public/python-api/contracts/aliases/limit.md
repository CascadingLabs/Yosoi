---
title: "Limit"
description: "yosoi.contracts.Limit Python API reference."
order: 0
---

`yosoi.contracts.Limit`

```python
Limit = Annotated[int, PydanticField(ge=0, le=2 ** 64 - 1, strict=True)]
```

Strict nonnegative u64 extraction or validation counter. Zero is a finite budget,
not an implicit unlimited setting.

[Source: python/yosoi/contracts.py:221](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/contracts.py#L221-L221)

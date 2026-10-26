---
title: "PositiveU32"
description: "yosoi.outcomes.PositiveU32 Python API reference."
order: 0
---

`yosoi.outcomes.PositiveU32`

```python
PositiveU32 = Annotated[int, Field(strict=True, gt=0, le=(1 << 32) - 1)]
```

Strict positive u32 integer. Zero and numeric coercions are rejected; units belong
to the consuming field.

[Source: python/yosoi/outcomes.py:33](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/outcomes.py#L33-L33)

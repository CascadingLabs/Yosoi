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

[Source: python/yosoi/outcomes.py:33](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/outcomes.py#L33-L33)

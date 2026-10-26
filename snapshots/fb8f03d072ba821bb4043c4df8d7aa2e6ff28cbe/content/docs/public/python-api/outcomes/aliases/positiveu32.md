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

[Source: python/yosoi/outcomes.py:33](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/outcomes.py#L33-L33)

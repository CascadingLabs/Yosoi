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

[Source: python/yosoi/contracts.py:176](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/contracts.py#L176-L176)

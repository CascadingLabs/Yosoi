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

[Source: python/yosoi/contracts.py:196](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/contracts.py#L196-L196)

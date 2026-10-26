---
title: "ReadOperation"
description: "yosoi.surface.ReadOperation Python API reference."
order: 0
---

`yosoi.surface.ReadOperation`

```python
ReadOperation = Annotated[Overview | Expand | Inspect | Search | Parent, Field(discriminator='kind')]
```

Tagged navigation operation; capabilities determine which variants are supported.

[Source: python/yosoi/surface.py:294](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L294-L296)

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

[Source: python/yosoi/surface.py:294](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L294-L296)

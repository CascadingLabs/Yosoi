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

[Source: python/yosoi/surface.py:294](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L294-L296)

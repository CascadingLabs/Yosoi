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

[Source: python/yosoi/surface.py:287](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L287-L289)

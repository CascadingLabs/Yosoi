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

[Source: python/yosoi/surface.py:294](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L294-L296)

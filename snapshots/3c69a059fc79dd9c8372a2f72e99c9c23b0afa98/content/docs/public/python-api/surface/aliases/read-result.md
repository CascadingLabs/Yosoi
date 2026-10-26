---
title: "ReadResult"
description: "yosoi.surface.ReadResult Python API reference."
order: 0
---

`yosoi.surface.ReadResult`

```python
ReadResult = Annotated[PageResult | InspectionResult | ParentResult, Field(discriminator='kind')]
```

Tagged result of a shared read. Contains evidence, never action authority.

[Source: python/yosoi/surface.py:363](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L363-L365)

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

[Source: python/yosoi/surface.py:370](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L370-L372)

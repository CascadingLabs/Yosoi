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

[Source: python/yosoi/surface.py:370](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L370-L372)

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

[Source: python/yosoi/surface.py:370](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L370-L372)

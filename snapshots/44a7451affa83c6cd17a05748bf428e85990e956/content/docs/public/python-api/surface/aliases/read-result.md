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

[Source: python/yosoi/surface.py:370](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L370-L372)

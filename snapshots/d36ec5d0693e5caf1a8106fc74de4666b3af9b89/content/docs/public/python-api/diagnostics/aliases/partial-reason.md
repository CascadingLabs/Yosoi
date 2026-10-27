---
title: "PartialReason"
description: "yosoi.diagnostics.PartialReason Python API reference."
order: 0
---

`yosoi.diagnostics.PartialReason`

```python
type PartialReason = Annotated[_PartialReasonUnit | _BrowserArtifactTruncated, Field(discriminator='kind')]
```

Why a retained representation is partial rather than complete evidence.

[Source: python/yosoi/diagnostics.py:88](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/diagnostics.py#L88-L90)

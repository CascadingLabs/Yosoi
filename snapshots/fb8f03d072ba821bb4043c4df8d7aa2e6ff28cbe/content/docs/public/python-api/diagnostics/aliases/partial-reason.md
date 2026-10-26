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

[Source: python/yosoi/diagnostics.py:88](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/diagnostics.py#L88-L90)

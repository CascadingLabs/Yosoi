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

[Source: python/yosoi/diagnostics.py:88](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/diagnostics.py#L88-L90)

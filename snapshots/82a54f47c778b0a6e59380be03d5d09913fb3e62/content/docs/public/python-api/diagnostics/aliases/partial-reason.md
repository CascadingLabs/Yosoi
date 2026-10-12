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

[Source: python/yosoi/diagnostics.py:88](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/diagnostics.py#L88-L90)

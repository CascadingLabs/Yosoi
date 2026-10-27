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

[Source: python/yosoi/diagnostics.py:88](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/diagnostics.py#L88-L90)

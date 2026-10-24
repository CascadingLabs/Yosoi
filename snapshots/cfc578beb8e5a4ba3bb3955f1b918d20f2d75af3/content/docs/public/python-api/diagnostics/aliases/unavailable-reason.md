---
title: "UnavailableReason"
description: "yosoi.diagnostics.UnavailableReason Python API reference."
order: 0
---

`yosoi.diagnostics.UnavailableReason`

```python
type UnavailableReason = Annotated[_UnavailableReasonUnit | _UnavailableArtifactReason, Field(discriminator='kind')]
```

Why requested evidence or its payload is unavailable to projection.

[Source: python/yosoi/diagnostics.py:113](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/diagnostics.py#L113-L116)

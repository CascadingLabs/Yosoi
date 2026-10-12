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

[Source: python/yosoi/diagnostics.py:113](https://github.com/CascadingLabs/Yosoi/blob/82a54f47c778b0a6e59380be03d5d09913fb3e62/python/yosoi/diagnostics.py#L113-L116)

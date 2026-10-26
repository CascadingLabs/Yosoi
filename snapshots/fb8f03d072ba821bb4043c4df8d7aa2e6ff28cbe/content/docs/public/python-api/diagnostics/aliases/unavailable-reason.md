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

[Source: python/yosoi/diagnostics.py:113](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/diagnostics.py#L113-L116)

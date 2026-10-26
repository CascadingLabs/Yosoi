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

[Source: python/yosoi/diagnostics.py:113](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/diagnostics.py#L113-L116)

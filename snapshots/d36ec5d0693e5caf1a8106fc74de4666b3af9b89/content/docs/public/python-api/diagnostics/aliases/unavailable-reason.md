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

[Source: python/yosoi/diagnostics.py:113](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/diagnostics.py#L113-L116)

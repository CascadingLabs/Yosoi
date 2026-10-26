---
title: "UnprojectableReason"
description: "yosoi.diagnostics.UnprojectableReason Python API reference."
order: 0
---

`yosoi.diagnostics.UnprojectableReason`

```python
type UnprojectableReason = Annotated[_UnprojectableReasonUnit | _UnknownSourceFormat | _DecodingReason | _CaptureArtifactUnprojectable, Field(discriminator='kind')]
```

Why retained source cannot produce the requested document representation.

[Source: python/yosoi/diagnostics.py:148](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/diagnostics.py#L148-L154)

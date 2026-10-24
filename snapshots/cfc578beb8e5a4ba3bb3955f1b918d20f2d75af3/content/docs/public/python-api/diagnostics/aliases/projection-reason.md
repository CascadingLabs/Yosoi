---
title: "ProjectionReason"
description: "yosoi.diagnostics.ProjectionReason Python API reference."
order: 0
---

`yosoi.diagnostics.ProjectionReason`

```python
type ProjectionReason = Annotated[PartialReason | UnavailableReason | UnprojectableReason, Field(discriminator='kind')]
```

Typed partial, unavailable, or unprojectable representation explanation.

[Source: python/yosoi/diagnostics.py:158](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/diagnostics.py#L158-L161)

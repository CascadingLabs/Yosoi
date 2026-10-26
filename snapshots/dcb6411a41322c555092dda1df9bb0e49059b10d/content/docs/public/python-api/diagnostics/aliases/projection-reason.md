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

[Source: python/yosoi/diagnostics.py:158](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/diagnostics.py#L158-L161)

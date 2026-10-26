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

[Source: python/yosoi/diagnostics.py:158](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/diagnostics.py#L158-L161)

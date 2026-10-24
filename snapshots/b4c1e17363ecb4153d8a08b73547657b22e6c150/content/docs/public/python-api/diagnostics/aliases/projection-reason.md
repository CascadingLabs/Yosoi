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

[Source: python/yosoi/diagnostics.py:158](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/diagnostics.py#L158-L161)

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

[Source: python/yosoi/diagnostics.py:158](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/diagnostics.py#L158-L161)

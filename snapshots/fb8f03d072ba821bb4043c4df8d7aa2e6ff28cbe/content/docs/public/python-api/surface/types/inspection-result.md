---
title: "InspectionResult"
description: "yosoi.surface.InspectionResult Python API reference."
order: 0
---

`yosoi.surface.InspectionResult`

```python
class InspectionResult(ImmutableModel):
```

Tagged shared detail result.

[Source: python/yosoi/surface.py:356](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L356-L360)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['inspection'] = Field(default='inspection', description='Result tag.')
data: Inspection = Field(description='Bounded evidence fragment.')
```

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

[Source: python/yosoi/surface.py:349](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L349-L353)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['inspection'] = Field(default='inspection', description='Result tag.')
data: Inspection = Field(description='Bounded evidence fragment.')
```

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

[Source: python/yosoi/surface.py:356](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L356-L360)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['inspection'] = Field(default='inspection', description='Result tag.')
data: Inspection = Field(description='Bounded evidence fragment.')
```

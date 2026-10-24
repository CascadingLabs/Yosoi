---
title: "Omission"
description: "yosoi.map.Omission Python API reference."
order: 0
---

`yosoi.map.Omission`

```python
class Omission(ImmutableModel):
```

Counted omission events, not all undiscovered site items.

Attributes:
    reason: Boundary or rejection classification causing the omission.
    count: Recorded event count for this category.

[Source: python/yosoi/map.py:536](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/map.py#L536-L545)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
reason: OmissionReason
count: int
```

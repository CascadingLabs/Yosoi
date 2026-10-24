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

[Source: python/yosoi/map.py:536](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/map.py#L536-L545)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
reason: OmissionReason
count: int
```

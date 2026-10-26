---
title: "Exploration"
description: "yosoi.map.Exploration Python API reference."
order: 0
---

`yosoi.map.Exploration`

```python
class Exploration(ImmutableModel):
```

Retained page exploration state, independent of discovery provenance.

Attributes:
    kind: inventoried means retained but unscheduled; pending means queued;
        inspected means supported inspection finished; skipped and failed retain
        their reasons.
    value: Skip reason or typed source failure when applicable, otherwise None.

[Source: python/yosoi/map.py:300](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/map.py#L300-L311)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['inventoried', 'pending', 'inspected', 'skipped', 'failed']
value: SkipReason | SourceFailure | None = None
```

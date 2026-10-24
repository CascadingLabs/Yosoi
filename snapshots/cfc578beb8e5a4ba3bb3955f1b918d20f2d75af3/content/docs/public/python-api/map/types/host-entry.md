---
title: "HostEntry"
description: "yosoi.map.HostEntry Python API reference."
order: 0
---

`yosoi.map.HostEntry`

```python
class HostEntry(ImmutableModel):
```

An admitted hostname with explicit reachability evidence.

Attributes:
    host: Canonical admitted hostname without a scheme or path.
    observations: Retained source evidence, bounded by policy.
    verification: unverified for discovery alone; http_observed for an observed HTTP
        response. Neither proves ownership, application success, or future
        availability.

[Source: python/yosoi/map.py:314](https://github.com/CascadingLabs/Yosoi/blob/cfc578beb8e5a4ba3bb3955f1b918d20f2d75af3/python/yosoi/map.py#L314-L327)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
host: str
observations: tuple[Observation, ...]
verification: Literal['unverified', 'http_observed']
```

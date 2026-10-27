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

[Source: python/yosoi/map.py:314](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/map.py#L314-L327)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
host: str
observations: tuple[Observation, ...]
verification: Literal['unverified', 'http_observed']
```

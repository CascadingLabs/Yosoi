---
title: "FrontierEntry"
description: "yosoi.map.FrontierEntry Python API reference."
order: 0
---

`yosoi.map.FrontierEntry`

```python
class FrontierEntry(ImmutableModel):
```

Unfinished page work, without a promise of later execution.

Attributes:
    page: Normalized URL whose work remains unfinished.
    reason: awaiting_exploration, depth_boundary, operation_stopped, or
        probe_candidate explains why no completed exploration is present.

[Source: python/yosoi/map.py:383](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/map.py#L383-L395)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
page: str
reason: Literal['awaiting_exploration', 'depth_boundary', 'operation_stopped', 'probe_candidate']
```

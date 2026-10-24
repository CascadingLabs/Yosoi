---
title: "MapTermination"
description: "yosoi.map.MapTermination Python API reference."
order: 0
---

`yosoi.map.MapTermination`

```python
class MapTermination(ImmutableModel):
```

Why discovery stopped, independently of individual source success.

Attributes:
    kind: exhausted means no runnable work remains under policy, not exhaustive site
        coverage; limit, deadline, and cancelled stop further work while retaining
        evidence.
    value: Resource limit classification for limit, otherwise None.

[Source: python/yosoi/map.py:480](https://github.com/CascadingLabs/Yosoi/blob/b4c1e17363ecb4153d8a08b73547657b22e6c150/python/yosoi/map.py#L480-L507)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
kind: Literal['exhausted', 'limit', 'deadline', 'cancelled']
value: Literal['hosts', 'urls', 'relationships', 'observations', 'pending', 'requests', 'sitemaps', 'sitemap_depth', 'response_bytes', 'total_response_bytes', 'inventory_bytes', 'parser_entries'] | None = Field(default=None, exclude_if=lambda value: value is None)
```

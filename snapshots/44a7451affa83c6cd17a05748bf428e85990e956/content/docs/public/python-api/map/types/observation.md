---
title: "Observation"
description: "yosoi.map.Observation Python API reference."
order: 0
---

`yosoi.map.Observation`

```python
class Observation(_MapOrderable):
```

One retained provenance observation, without a reachability guarantee.

Attributes:
    source: Mechanism reporting the host, page, or wildcard.
    source_url: Reporting page or endpoint, or None when no URL applies.

[Source: python/yosoi/map.py:261](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/map.py#L261-L272)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
source: DiscoverySource
source_url: str | None
```

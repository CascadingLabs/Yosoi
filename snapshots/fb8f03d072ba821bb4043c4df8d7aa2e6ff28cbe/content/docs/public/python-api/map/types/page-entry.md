---
title: "PageEntry"
description: "yosoi.map.PageEntry Python API reference."
order: 0
---

`yosoi.map.PageEntry`

```python
class PageEntry(ImmutableModel):
```

Normalized page URL with discovery and exploration evidence.

Attributes:
    url: Admitted normalized HTTP(S) URL with fragments removed.
    minimum_link_depth: Smallest known rooted link depth, or None when not
        established.
    observations: Retained provenance observations, bounded by policy.
    exploration: Whether the page was inventoried, inspected, skipped, failed, or
        remains pending.

[Source: python/yosoi/map.py:330](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/map.py#L330-L345)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
url: str
minimum_link_depth: int | None
observations: tuple[Observation, ...]
exploration: Exploration
```

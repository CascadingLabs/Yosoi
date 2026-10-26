---
title: "WildcardEntry"
description: "yosoi.map.WildcardEntry Python API reference."
order: 0
---

`yosoi.map.WildcardEntry`

```python
class WildcardEntry(ImmutableModel):
```

A retained wildcard pattern without expansion into guessed hosts.

Attributes:
    pattern: Observed wildcard name, not a verified concrete hostname.
    observations: Retained reporting sources, subject to evidence budgets.

[Source: python/yosoi/map.py:348](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/map.py#L348-L357)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
pattern: str
observations: tuple[Observation, ...]
```

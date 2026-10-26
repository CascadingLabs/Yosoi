---
title: "ArchiveLimits"
description: "yosoi.surface.ArchiveLimits Python API reference."
order: 0
---

`yosoi.surface.ArchiveLimits`

```python
class ArchiveLimits(ImmutableModel):
```

Retention bounds separate from live history and response budgets.

[Source: python/yosoi/surface.py:872](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L872-L895)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
bytes: int = Field(default=64 * 1024 * 1024, strict=True, ge=1, le=128 * 1024 * 1024, description='Combined original evidence byte limit.')
observations: int = Field(default=256, strict=True, ge=1, le=4096, description='Maximum retained sources and artifacts.')
operations: int = Field(default=4096, strict=True, ge=1, le=4096, description='Maximum retained receipts.')
```

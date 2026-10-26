---
title: "SurfacePolicy"
description: "yosoi.surface.SurfacePolicy Python API reference."
order: 0
---

`yosoi.surface.SurfacePolicy`

```python
class SurfacePolicy(ImmutableModel):
```

Evidence retention and output bounds shared across source connections.

[Source: python/yosoi/surface.py:1092](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1092-L1109)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
archive: ArchivePolicy = Field(default='off', description='Portable outcome retention, disabled by default.')
archive_limits: ArchiveLimits = Field(default_factory=ArchiveLimits, description='Evidence limits independent of response budgets.')
archive_root: Path | None = Field(default=None, description='Durable checkpoint store; otherwise owned temporary storage.')
output: Path | None = Field(default=None, description='Durable trace directory; otherwise owned temporary files.')
```

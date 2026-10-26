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

[Source: python/yosoi/surface.py:1092](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L1092-L1109)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
archive: ArchivePolicy = Field(default='off', description='Portable outcome retention, disabled by default.')
archive_limits: ArchiveLimits = Field(default_factory=ArchiveLimits, description='Evidence limits independent of response budgets.')
archive_root: Path | None = Field(default=None, description='Durable checkpoint store; otherwise owned temporary storage.')
output: Path | None = Field(default=None, description='Durable trace directory; otherwise owned temporary files.')
```

---
title: "SessionPolicy"
description: "yosoi.surface.SessionPolicy Python API reference."
order: 0
---

`yosoi.surface.SessionPolicy`

```python
class SessionPolicy(ImmutableModel):
```

Bounds for in-memory readers, subscriptions, history and one hot owner.

[Source: python/yosoi/surface.py:1236](https://github.com/CascadingLabs/Yosoi/blob/d36ec5d0693e5caf1a8106fc74de4666b3af9b89/python/yosoi/surface.py#L1236-L1258)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
archive: ArchivePolicy = Field(default='off', description='Explicit evidence retention for Archive saving.')
archive_limits: ArchiveLimits = Field(default_factory=ArchiveLimits, description='Portable outcome bounds independent of live history.')
cursors: int = Field(default=1, strict=True, ge=0, description='Logical cursor cap.')
watches: int = Field(default=8, strict=True, ge=0, description='Total region watch cap.')
captures: int = Field(default=2, strict=True, ge=0, description='Retained capture count.')
events: int = Field(default=128, strict=True, ge=0, description='Event history capacity.')
```

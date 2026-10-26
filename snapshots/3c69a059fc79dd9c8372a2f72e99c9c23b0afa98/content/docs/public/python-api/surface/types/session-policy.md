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

[Source: python/yosoi/surface.py:861](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L861-L875)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
cursors: int = Field(default=1, strict=True, ge=0, description='Logical cursor cap.')
watches: int = Field(default=8, strict=True, ge=0, description='Total region watch cap.')
captures: int = Field(default=2, strict=True, ge=0, description='Retained capture count.')
events: int = Field(default=128, strict=True, ge=0, description='Event history capacity.')
```

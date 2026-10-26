---
title: "EventBatch"
description: "yosoi.surface.EventBatch Python API reference."
order: 0
---

`yosoi.surface.EventBatch`

```python
class EventBatch(ImmutableModel):
```

Unread bounded session history with an explicit missed-events flag.

[Source: python/yosoi/surface.py:958](https://github.com/CascadingLabs/Yosoi/blob/3c69a059fc79dd9c8372a2f72e99c9c23b0afa98/python/yosoi/surface.py#L958-L964)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
events: tuple[Event, ...] = Field(description='Retained events since the last read.')
lost: StrictBool = Field(description='Whether older unread events were evicted.')
```

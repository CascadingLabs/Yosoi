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

[Source: python/yosoi/surface.py:1341](https://github.com/CascadingLabs/Yosoi/blob/dcb6411a41322c555092dda1df9bb0e49059b10d/python/yosoi/surface.py#L1341-L1347)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
events: tuple[Event, ...] = Field(description='Retained events since the last read.')
lost: StrictBool = Field(description='Whether older unread events were evicted.')
```

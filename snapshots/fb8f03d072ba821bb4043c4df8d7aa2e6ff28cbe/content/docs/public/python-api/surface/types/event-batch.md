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

[Source: python/yosoi/surface.py:1341](https://github.com/CascadingLabs/Yosoi/blob/fb8f03d072ba821bb4043c4df8d7aa2e6ff28cbe/python/yosoi/surface.py#L1341-L1347)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
events: tuple[Event, ...] = Field(description='Retained events since the last read.')
lost: StrictBool = Field(description='Whether older unread events were evicted.')
```

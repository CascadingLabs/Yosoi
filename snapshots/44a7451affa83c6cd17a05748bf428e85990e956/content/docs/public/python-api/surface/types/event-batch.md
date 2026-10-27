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

[Source: python/yosoi/surface.py:1341](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L1341-L1347)

Members below are declared on this class. Inherited Pydantic methods and generated constructor signatures are not expanded.

## Fields and class attributes

```python
events: tuple[Event, ...] = Field(description='Retained events since the last read.')
lost: StrictBool = Field(description='Whether older unread events were evicted.')
```
